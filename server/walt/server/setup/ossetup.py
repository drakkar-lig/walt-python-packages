import base64
import datetime
import gzip
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import requests
from pkg_resources import resource_filename
from walt.common.version import __version__
from walt.server.setup.apt import (
    autoremove_packages,
    fix_dpkg_options,
    get_debconf_selection,
    package_is_installed,
    remove_packages,
    set_debconf_selection,
    upgrade_and_install_packages,
)
from walt.server.setup.grub import get_grub_boot_disk

DOCKER_REPO_URL = "https://download.docker.com/linux/debian"
DOCKER_KEYRING_FILE = Path("/usr/share/keyrings/docker-archive-keyring.gpg")

APT_SOURCES_LIST_CONTENT = """\
deb http://deb.D.org/D/ R main contrib non-free
deb-src http://deb.D.org/D/ R main contrib non-free

deb http://security.D.org/D-security R-security main contrib non-free
deb-src http://security.D.org/D-security R-security main contrib non-free

# R-updates, to get updates before a point release is made;
# see https://www.D.org/doc/manuals/D-reference/ch02.en.html#_updates_and_backports
deb http://deb.D.org/D/ R-updates main contrib non-free
deb-src http://deb.D.org/D/ R-updates main contrib non-free
""".replace("D", "debian").replace("R", "bullseye")

APT_DOCKER_LIST_CONTENT = f"""\
deb [arch=amd64 signed-by={DOCKER_KEYRING_FILE}] {DOCKER_REPO_URL} bullseye stable
"""

# in case of distribution upgrade, remove old versions of packages (including their
# configuration files)
# this includes:
# - old versions of docker packages
# - old versions of buildah, podman and their dependencies which were provided through
#   a different apt repo on buster
# - network services for which walt installation changed their configuration files
#   (walt now uses its own conf files for these services, stored in
#   /var/lib/walt/services, and does not need anymore to touch the default
#   configuration files of these services)
# up-to-date versions of these packages will be reinstalled in a next step.
APT_OLD_DIST_PACKAGES = """
docker docker-engine docker.io containerd runc containers-image containers-common
buildah podman containernetworking-plugins conmon podman-plugins slirp4netns crun
isc-dhcp-server tftpd-hpa ptpd lldpd snmpd
""".split()

APT_WALT_DEPENDENCIES_PACKAGES = """
        apt-transport-https ca-certificates gnupg2 curl gnupg-agent
        software-properties-common binfmt-support qemu-user-static
        lldpd snmp snmpd openssh-server snmp-mibs-downloader iputils-ping
        libsmi2-dev isc-dhcp-server nfs-kernel-server uuid-runtime postgresql
        ntpdate ntp lockfile-progs ptpd tftpd-hpa ebtables qemu-system-x86 bridge-utils
        screen ifupdown gcc python3-dev git make sudo expect netcat libjson-perl
        docker-ce docker-ce-cli containerd.io podman buildah skopeo bash-completion
""".split()


def get_os_codename():
    release_file = Path("/etc/os-release")
    if not release_file.exists():
        raise Exception("File /etc/os-release not found.")
    for line in release_file.read_text().splitlines():
        name, value = shlex.split(line.replace("=", " ", 1))
        if name == "VERSION_CODENAME":
            return value
    raise Exception("File /etc/os-release has no VERSION_CODENAME specified.")


def fix_apt_sources(silent_override=False):
    # prepare backup dir
    timestamp_str = datetime.datetime.now().strftime("%m%d%y%H%M%S")
    apt_backup_dir = Path(f"/etc/apt.backups/{timestamp_str}")
    # update /etc/apt/sources.list
    sources_list = Path("/etc/apt/sources.list")
    if sources_list.read_text() != APT_SOURCES_LIST_CONTENT:
        if not silent_override:
            sources_list_backup = apt_backup_dir / "sources.list"
            print(f"Updating {sources_list} (backup at {sources_list_backup})")
            apt_backup_dir.mkdir(parents=True, exist_ok=True)
            sources_list.rename(sources_list_backup)
        sources_list.write_text(APT_SOURCES_LIST_CONTENT)
    # update /etc/apt/sources.list.d
    sources_list_d = Path("/etc/apt/sources.list.d")
    docker_list = sources_list_d / "docker.list"
    if not docker_list.exists() or docker_list.read_text() != APT_DOCKER_LIST_CONTENT:
        if not silent_override:
            sources_list_d_backup = apt_backup_dir / "sources.list.d"
            print(f"Replacing {sources_list_d} (backup at {sources_list_d_backup})")
            sources_list_d.rename(sources_list_d_backup)
            sources_list_d.mkdir()
        docker_list.write_text(APT_DOCKER_LIST_CONTENT)


def ascii_dearmor(in_text):  # python-equivalent to: gpg --dearmor
    return base64.b64decode(in_text.split("-----")[2].rsplit("=", maxsplit=1)[0])


def fix_keyring(url, keyring_file):
    resp = requests.get(url)
    if not resp.ok:
        raise Exception(f"Failed to fetch {url}: {resp.reason}")
    keyring_file_content = ascii_dearmor(resp.text)
    if not keyring_file.exists() or keyring_file.read_bytes() != keyring_file_content:
        print(f"Updating {keyring_file}")
        keyring_file.parent.mkdir(parents=True, exist_ok=True)
        keyring_file.write_bytes(keyring_file_content)


def fix_docker_keyring():
    fix_keyring(f"{DOCKER_REPO_URL}/gpg", DOCKER_KEYRING_FILE)


def fix_grub_pc():
    # on our pre-installed images, grub-install was called manually on the target disk
    # image, thus package "grub-pc" did not have its debconf entries filled in by the
    # user. As a result, when upgrading this package dpkg will ask on which device(s)
    # grub-install should be run.
    # here, we try to detect the boot disk and prefill this debconf entry.
    # first, verify package grub-pc is installed (might not be the case on an
    # UEFI server)
    if not package_is_installed("grub-pc"):
        return  # nothing to do
    # check if the debconf entry was not already filled in
    debconf_value = get_debconf_selection("grub-pc", "grub-pc/install_devices")
    if debconf_value is not None:
        return  # already filled in, nothing to do
    # try to detect boot disk
    boot_disk = get_grub_boot_disk()
    if boot_disk is None:
        # detection failed
        print(
            "Note: could not detect grub boot disk. Upgrade process will ask when"
            " needed."
        )
        return
    set_debconf_selection(
        "grub-pc", "grub-pc/install_devices", "multiselect", boot_disk
    )
    print("Updated package manager configuration about grub boot disk.")


def fix_packets(upgrade_dist=False, upgrade_packets=False):
    if upgrade_dist:
        remove_packages(APT_OLD_DIST_PACKAGES, purge=True)
    upgrade_and_install_packages(
        APT_WALT_DEPENDENCIES_PACKAGES, upgrade_packets=upgrade_packets
    )
    if upgrade_dist:
        autoremove_packages()


def upgrade_db():
    clusters_info = json.loads(
        subprocess.run(
            "pg_lsclusters -j".split(), check=True, stdout=subprocess.PIPE
        ).stdout
    )
    num_clusters = len(clusters_info)
    if num_clusters != 2:
        raise Exception(
            "Expected 2 db clusters after os upgrade, but pg_lsclusters lists"
            f" {num_clusters} cluster(s)!"
        )
    for c_info in clusters_info:
        if int(c_info["port"]) == 5432:  # default postgresql port => walt
            # database cluster
            old_version = c_info["version"]
        else:
            new_version = c_info["version"]
    print(
        f"Upgrading postgresql database version {old_version} to {new_version}... ",
        end="",
    )
    sys.stdout.flush()
    subprocess.run(
        f"pg_dropcluster --stop {new_version} main".split(),
        check=True,
        stdout=subprocess.PIPE,
    )
    subprocess.run(
        f"pg_upgradecluster {old_version} main".split(),
        check=True,
        stdout=subprocess.PIPE,
    )
    subprocess.run(
        f"pg_dropcluster {old_version} main".split(), check=True, stdout=subprocess.PIPE
    )
    print("done")


def upgrade_os():
    fix_apt_sources()
    fix_docker_keyring()
    fix_dpkg_options()
    fix_grub_pc()
    fix_packets(upgrade_dist=True, upgrade_packets=True)
    upgrade_db()
    # the virtualenv was built from an older version of python3,
    # upgrade it, and reinstall the packages in lib/python3.<new>/site-packages/
    print("Upgrading virtual env (python was updated by OS upgrade)... ", end="")
    sys.stdout.flush()
    subprocess.run(
        f"python3 -m venv --upgrade {sys.prefix}".split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    pip_install = f"{sys.prefix}/bin/pip install"
    subprocess.run(
        f"{pip_install} --upgrade pip".split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    if __version__.startswith("0."):
        # dev version, published on testpypi
        repo_opts = ("--index-url https://pypi.org/simple"
                     " --extra-index-url https://test.pypi.org/simple")
    else:
        repo_opts = ""
    subprocess.run(
        (f"{pip_install} {repo_opts}"
         f" walt-server=={__version__} walt-client=={__version__}").split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    print("done")


def fix_os():
    fix_dpkg_options()
    fix_grub_pc()
    fix_packets()


def install_os():
    fix_apt_sources()
    fix_docker_keyring()
    fix_dpkg_options()
    fix_grub_pc()
    fix_packets()


def install_os_on_image():
    fix_apt_sources(silent_override=True)
    fix_docker_keyring()
    fix_dpkg_options()
    fix_packets(upgrade_packets=True)  # have up-to-date packets on image


def has_diversion(path):
    diversion = subprocess.run(
        f"dpkg-divert --list {path}".split(), stdout=subprocess.PIPE
    ).stdout.strip()
    return len(diversion) > 0


def divert(path, diverted_path):
    subprocess.run(
        f"dpkg-divert --divert {diverted_path} --rename {path}".split(),
        check=True,
        stdout=subprocess.PIPE,
    )


# 'conmon' binary distributed in bullseye has a serious issue
# causing possibly truncated stdout in podman [run|exec]).
# we replace it with a more up-to-date binary statically compiled
# using the nix-based method.
def fix_conmon():
    if not has_diversion("/usr/bin/conmon"):
        print("Fixing issue with conmon tool... ", end="")
        sys.stdout.flush()
        divert("/usr/bin/conmon", "/usr/bin/conmon.distrib")
        conmon_gz_path = resource_filename(__name__, "conmon.gz")
        conmon_gz_content = Path(conmon_gz_path).read_bytes()
        conmon_content = gzip.decompress(conmon_gz_content)
        conmon_fixed_path = Path("/usr/bin/conmon.fixed")
        conmon_fixed_path.write_bytes(conmon_content)
        conmon_fixed_path.chmod(0o755)
        print("done")
        Path("/usr/bin/conmon").symlink_to("/usr/bin/conmon.fixed")


# We now install walt python packages in a virtual environment
# (at least for the server).
# Previously they were installed in the base python environment of the OS.
# This procedure cleans up any walt python package found there,
# and any obsolete vitrual environment.
def cleanup_old_walt_install():
    # we temporarily remove the venv prefix from the PATH variable,
    # to target the python executable of the base environment of the OS.
    saved_path = os.environ["PATH"]
    os.environ["PATH"] = ":".join(
        path_entry
        for path_entry in os.environ["PATH"].split(":")
        if not path_entry.startswith(sys.prefix)
    )
    print("Looking for obsolete walt packages... ", end="")
    sys.stdout.flush()
    proc = subprocess.run(
        "python3 -m pip list --format json".split(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print("done")
    # pip may not be installed on the base system, in this case the previous
    # command fails, but we know there are no obsolete pip packages there.
    if proc.returncode == 0:  # if previous command succeeded
        walt_packages = []
        for package_info in json.loads(proc.stdout):
            package_name = package_info["name"]
            if package_name.startswith("walt-"):
                walt_packages.append(package_name)
        if len(walt_packages) > 0:
            print("Removing obsolete walt packages... ", end="")
            sys.stdout.flush()
            subprocess.run(
                "python3 -m pip uninstall -y".split() + walt_packages,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("done")
    # restore the PATH variable
    os.environ["PATH"] = saved_path
    # clear old /opt/walt-<version> directories
    for opt_entry in Path('/opt').iterdir():
        if opt_entry.name.startswith('walt-') and opt_entry != Path(sys.prefix):
            print(f"Removing obsolete {opt_entry}... ", end="")
            sys.stdout.flush()
            shutil.rmtree(str(opt_entry))
            print("done")
