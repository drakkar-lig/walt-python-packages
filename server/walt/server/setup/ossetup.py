import base64
import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import requests
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
deb http://deb.D.org/D/ R C
deb-src http://deb.D.org/D/ R C

deb http://deb.D.org/D-security R-security C
deb-src http://deb.D.org/D-security R-security C

# R-updates, to get updates before a point release is made;
# see https://www.D.org/doc/manuals/D-reference/ch02.en.html#_updates_and_backports
deb http://deb.D.org/D/ R-updates C
deb-src http://deb.D.org/D/ R-updates C
""".replace(
    "D", "debian"
).replace(
    "R", "bookworm"
).replace(
    "C", "main contrib non-free non-free-firmware")

APT_DEBIAN_SOURCES_CONTENT = """\
Types: deb deb-src
URIs: http://deb.debian.org/debian
Suites: RELEASE RELEASE-updates
Components: COMPONENTS
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb deb-src
URIs: http://deb.debian.org/debian-security
Suites: RELEASE-security
Components: COMPONENTS
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
""".replace(
    "RELEASE", "bookworm"
).replace(
    "COMPONENTS", "main contrib non-free non-free-firmware")

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
docker docker-engine docker-ce docker-ce-cli containerd containerd.io docker.io
runc containers-image containers-common buildah podman containernetworking-plugins
conmon podman-plugins slirp4netns crun isc-dhcp-server tftpd-hpa ptpd lldpd snmpd
""".split()

APT_WALT_DEPENDENCIES_PACKAGES = """
        apt-transport-https ca-certificates gnupg2 curl gnupg-agent
        software-properties-common binfmt-support qemu-user-static
        lldpd snmp snmpd openssh-server snmp-mibs-downloader iputils-ping
        libsmi2-dev isc-dhcp-server bind9 nfs-kernel-server postgresql
        ntpdate ntp lockfile-progs ptpd tftpd-hpa ebtables bridge-utils
        screen ifupdown gcc python3-dev git make sudo expect libjson-perl
        docker.io podman buildah skopeo bash-completion dropbear-bin
        ksmtuned fdisk e2fsprogs dosfstools containernetworking-plugins
        uuid-runtime qemu-system-x86 netcat-openbsd lsof
""".split()

# note: containernetworking-plugins is needed for "walt image build".
# for some reason, it seems to be missing from the dependencies of buildah.

UPGRADE_STATUS_FILE = Path("/var/lib/walt/.upgrade")


def record_start_os_upgrade():
    # if the upgrade fails, the file /var/lib/walt/.upgrade will
    # indicate which debian version was being updated, so that
    # if walt-server-setup is called again, it retries the full
    # upgrade (and disregard the content of /etc/os-release possibly
    # already indicating the target OS version is there).
    if not UPGRADE_STATUS_FILE.exists():
        codename = get_os_codename()
        UPGRADE_STATUS_FILE.write_text(codename)


def record_end_os_upgrade():
    UPGRADE_STATUS_FILE.unlink()


def get_os_codename():
    # if the previous call to walt-server-setup failed in the
    # middle of the OS upgrade, disregard the content of file
    # /etc/os-release, and consider we are still running the old
    # OS version instead, in order to retry the full OS upgrade.
    if UPGRADE_STATUS_FILE.exists():
        return UPGRADE_STATUS_FILE.read_text()
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
    # check which updates are needed
    sources_list = Path("/etc/apt/sources.list")
    sources_list_d = Path("/etc/apt/sources.list.d")
    debian_sources = sources_list_d / "debian.sources"
    obsolete_docker_list = sources_list_d / "docker.list"
    update_apt_sources_list, update_apt_sources_list_d = False, False
    debian_sources_mode = debian_sources.exists()
    if debian_sources_mode:
        # new distribution using a deb822-style file at sources.list.d/debian.sources
        if debian_sources.read_text() != APT_DEBIAN_SOURCES_CONTENT:
            update_apt_sources_list_d = True
    else:
        # old distribution, or new distribution manually updated, using
        # old-style sources.list
        if sources_list.read_text() != APT_SOURCES_LIST_CONTENT:
            update_apt_sources_list = True
    if obsolete_docker_list.exists():
        update_apt_sources_list_d = True
    # update /etc/apt/sources.list
    if update_apt_sources_list:
        if not silent_override:
            sources_list_backup = apt_backup_dir / "sources.list"
            print(f"Updating {sources_list} (backup at {sources_list_backup})")
            apt_backup_dir.mkdir(parents=True, exist_ok=True)
            sources_list.rename(sources_list_backup)
        sources_list.write_text(APT_SOURCES_LIST_CONTENT)
    # update /etc/apt/sources.list.d
    if update_apt_sources_list_d:
        if not silent_override:
            sources_list_d_backup = apt_backup_dir / "sources.list.d"
            print(f"Replacing {sources_list_d} (backup at {sources_list_d_backup})")
            sources_list_d_backup.mkdir(parents=True, exist_ok=True)
            sources_list_d.rename(sources_list_d_backup)
            sources_list_d.mkdir()
        if obsolete_docker_list.exists():
            obsolete_docker_list.unlink()
        if debian_sources_mode:
            debian_sources.write_text(APT_DEBIAN_SOURCES_CONTENT)


def ascii_dearmor(in_text):  # python-equivalent to: gpg --dearmor
    return base64.b64decode(in_text.split("-----")[2].rsplit("=", maxsplit=1)[0])


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
    # Note: if upgrading the distribution, first upgrade the packages
    # from the new repo, then install packages walt needs.
    # Doing it as a single step may cause dependency problems.
    if upgrade_dist:
        remove_packages(APT_OLD_DIST_PACKAGES, purge=True)
        upgrade_and_install_packages("OS upgrade", [], upgrade_packets=True)
    upgrade_and_install_packages(
        "WalT dependencies",
        APT_WALT_DEPENDENCIES_PACKAGES,
        upgrade_packets=upgrade_packets
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
    try:
        fix_apt_sources()
        fix_dpkg_options()
        fix_grub_pc()
        fix_packets(upgrade_dist=True, upgrade_packets=True)
    finally:
        # The virtualenv was built from an older version of python3,
        # upgrade it, and reinstall the packages in lib/python3.<new>/site-packages/.
        # Even if the apt package upgrades failed (unfortunately, a rather common
        # issue), the python3 package may still have been updated, so enclose this
        # in the finally block because if walt-server-setup is called again,
        # it will require a working venv.
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
    upgrade_db()


def fix_os():
    fix_apt_sources()
    fix_dpkg_options()
    fix_grub_pc()
    fix_packets()


def install_os():
    fix_apt_sources()
    fix_dpkg_options()
    fix_grub_pc()
    fix_packets()


def install_os_on_image():
    fix_apt_sources(silent_override=True)
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


def undivert(path):
    subprocess.run(
        f"dpkg-divert --rename --remove {path}".split(),
        check=True,
        stdout=subprocess.PIPE,
    )


# 'conmon' binary distributed in bullseye had a serious issue
# causing possibly truncated stdout in podman [run|exec]).
# We used dpkg-divert to replace it with a statically compiled
# binary. Now with bookworm, we can revert to the distribution-
# provided binary.
def fix_conmon():
    if has_diversion("/usr/bin/conmon"):
        print("Restoring conmon tool previously diverted... ", end="")
        sys.stdout.flush()
        Path("/usr/bin/conmon").unlink()
        Path("/usr/bin/conmon.fixed").unlink()
        undivert("/usr/bin/conmon")
        print("done")


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
    print("Looking for obsolete WalT packages... ", end="")
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
            print("Removing obsolete WalT packages... ", end="")
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
