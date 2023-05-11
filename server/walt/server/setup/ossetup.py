import shlex, datetime, requests, subprocess, json, sys, gzip, base64
from pathlib import Path
from pkg_resources import resource_filename
from walt.common.version import __version__ as WALT_VERSION
from walt.server.setup.pip import install_pip, pip
from walt.server.setup.apt import fix_dpkg_options, package_is_installed, get_debconf_selection, \
                                  set_debconf_selection, remove_packages, upgrade_and_install_packages, \
                                  autoremove_packages
from walt.server.setup.grub import get_grub_boot_disk

DOCKER_REPO_URL     = "https://download.docker.com/linux/debian"
DOCKER_KEYRING_FILE = Path("/usr/share/keyrings/docker-archive-keyring.gpg")

APT_SOURCES_LIST_CONTENT = """\
deb http://deb.debian.org/debian/ bullseye main contrib non-free
deb-src http://deb.debian.org/debian/ bullseye main contrib non-free

deb http://security.debian.org/debian-security bullseye-security main contrib non-free
deb-src http://security.debian.org/debian-security bullseye-security main contrib non-free

# bullseye-updates, to get updates before a point release is made;
# see https://www.debian.org/doc/manuals/debian-reference/ch02.en.html#_updates_and_backports
deb http://deb.debian.org/debian/ bullseye-updates main contrib non-free
deb-src http://deb.debian.org/debian/ bullseye-updates main contrib non-free
"""

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
#   (walt now uses its own conf files for these services, stored in /var/lib/walt/services,
#   and does not need anymore to touch the default configuration files of these services)
# up-to-date versions of these packages will be reinstalled in a next step.
APT_OLD_DIST_PACKAGES = """
docker docker-engine docker.io containerd runc containers-image containers-common buildah podman
containernetworking-plugins conmon podman-plugins slirp4netns crun
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
    release_file = Path('/etc/os-release')
    if not release_file.exists():
        raise Exception('File /etc/os-release not found.')
    for line in release_file.read_text().splitlines():
        name, value = shlex.split(line.replace('=', ' ', 1))
        if name == 'VERSION_CODENAME':
            return value
    raise Exception('File /etc/os-release has no VERSION_CODENAME specified.')

def fix_apt_sources(silent_override = False):
    # prepare backup dir
    timestamp_str = datetime.datetime.now().strftime("%m%d%y%H%M%S")
    apt_backup_dir = Path(f'/etc/apt.backups/{timestamp_str}')
    # update /etc/apt/sources.list
    sources_list = Path('/etc/apt/sources.list')
    if sources_list.read_text() != APT_SOURCES_LIST_CONTENT:
        if not silent_override:
            sources_list_backup = apt_backup_dir / 'sources.list'
            print(f'Updating {sources_list} (backup at {sources_list_backup})')
            apt_backup_dir.mkdir(parents=True, exist_ok=True)
            sources_list.rename(sources_list_backup)
        sources_list.write_text(APT_SOURCES_LIST_CONTENT)
    # update /etc/apt/sources.list.d
    sources_list_d = Path('/etc/apt/sources.list.d')
    docker_list = sources_list_d / 'docker.list'
    if not docker_list.exists() or \
       docker_list.read_text() != APT_DOCKER_LIST_CONTENT:
        if not silent_override:
            sources_list_d_backup = apt_backup_dir / 'sources.list.d'
            print(f'Replacing {sources_list_d} (backup at {sources_list_d_backup})')
            sources_list_d.rename(sources_list_d_backup)
            sources_list_d.mkdir()
        docker_list.write_text(APT_DOCKER_LIST_CONTENT)

def ascii_dearmor(in_text):  # python-equivalent to: gpg --dearmor
    return base64.b64decode(in_text.split('-----')[2].rsplit('=', maxsplit=1)[0])

def fix_keyring(url, keyring_file):
    resp = requests.get(url)
    if not resp.ok:
        raise Exception(f'Failed to fetch {url}: {resp.reason}')
    keyring_file_content = ascii_dearmor(resp.text)
    if not keyring_file.exists() or \
       keyring_file.read_bytes() != keyring_file_content:
        print(f'Updating {keyring_file}')
        keyring_file.parent.mkdir(parents=True, exist_ok=True)
        keyring_file.write_bytes(keyring_file_content)

def fix_docker_keyring():
    fix_keyring(f'{DOCKER_REPO_URL}/gpg', DOCKER_KEYRING_FILE)

def fix_grub_pc():
    # on our pre-installed images, grub-install was called manually on the target disk
    # image, thus package "grub-pc" did not have its debconf entries filled in by the
    # user. As a result, when upgrading this package dpkg will ask on which device(s)
    # grub-install should be run.
    # here, we try to detect the boot disk and prefill this debconf entry.
    # first, verify package grub-pc is installed (might not be the case on an UEFI server)
    if not package_is_installed('grub-pc'):
        return  # nothing to do
    # check if the debconf entry was not already filled in
    debconf_value = get_debconf_selection('grub-pc', 'grub-pc/install_devices')
    if debconf_value is not None:
        return  # already filled in, nothing to do
    # try to detect boot disk
    boot_disk = get_grub_boot_disk()
    if boot_disk is None:
        # detection failed
        print('Note: could not detect grub boot disk. Upgrade process will ask when needed.')
        return
    set_debconf_selection('grub-pc', 'grub-pc/install_devices', 'multiselect', boot_disk)
    print('Updated package manager configuration about grub boot disk.')

def fix_packets(upgrade_dist = False, upgrade_packets = False):
    if upgrade_dist:
        remove_packages(APT_OLD_DIST_PACKAGES, purge=True)
    upgrade_and_install_packages(APT_WALT_DEPENDENCIES_PACKAGES, upgrade_packets = upgrade_packets)
    if upgrade_dist:
        autoremove_packages()

def upgrade_db():
    clusters_info = json.loads(
        subprocess.run('pg_lsclusters -j'.split(),
                       check=True,
                       stdout=subprocess.PIPE).stdout)
    num_clusters = len(clusters_info)
    if num_clusters != 2:
        raise Exception(f"Expected 2 db clusters after os upgrade, but pg_lsclusters lists {num_clusters} cluster(s)!")
    for c_info in clusters_info:
        if int(c_info['port']) == 5432:  # default postgresql port => walt database cluster
            old_version = c_info['version']
        else:
            new_version = c_info['version']
    print(f'Upgrading postgresql database version {old_version} to {new_version}... ', end=''); sys.stdout.flush()
    subprocess.run(f'pg_dropcluster --stop {new_version} main'.split(),
                       check=True,
                       stdout=subprocess.PIPE)
    subprocess.run(f'pg_upgradecluster {old_version} main'.split(),
                       check=True,
                       stdout=subprocess.PIPE)
    subprocess.run(f'pg_dropcluster {old_version} main'.split(),
                       check=True,
                       stdout=subprocess.PIPE)
    print('done')

def reinstall_walt():
    dev_mode_repo = Path('/root/walt-python-packages')
    if dev_mode_repo.exists():
        # dev mode
        subprocess.run('make install'.split(),
                       cwd=dev_mode_repo,
                       check=True,
                       stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    else:
        # prod mode
        pip.install(f'walt-server=={WALT_VERSION} walt-client=={WALT_VERSION}')

def upgrade_os():
    fix_apt_sources()
    fix_docker_keyring()
    fix_dpkg_options()
    fix_grub_pc()
    fix_packets(upgrade_dist = True, upgrade_packets = True)
    upgrade_db()
    # existing python modules belong to the old version of python,
    # we have to reinstall them on the new version
    print('Re-installing pip (python was updated by OS upgrade)... ', end=''); sys.stdout.flush()
    install_pip()
    print('done')
    print('Re-installing walt software (python was updated by OS upgrade)... ', end=''); sys.stdout.flush()
    reinstall_walt()
    print('done')

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
    fix_apt_sources(silent_override = True)
    fix_docker_keyring()
    fix_dpkg_options()
    fix_packets(upgrade_packets = True)     # have up-to-date packets on image

def has_diversion(path):
    diversion = subprocess.run(f'dpkg-divert --list {path}'.split(),
                   stdout=subprocess.PIPE).stdout.strip()
    return len(diversion) > 0

def divert(path, diverted_path):
    subprocess.run(f'dpkg-divert --divert {diverted_path} --rename {path}'.split(),
                   check=True, stdout=subprocess.PIPE)

# 'conmon' binary distributed in bullseye has a serious issue
# causing possibly truncated stdout in podman [run|exec]).
# we replace it with a more up-to-date binary statically compiled
# using the nix-based method.
def fix_conmon():
    if not has_diversion('/usr/bin/conmon'):
        print('Fixing issue with conmon tool... ', end=''); sys.stdout.flush()
        divert('/usr/bin/conmon', '/usr/bin/conmon.distrib')
        conmon_gz_path = resource_filename(__name__, 'conmon.gz')
        conmon_gz_content = Path(conmon_gz_path).read_bytes()
        conmon_content = gzip.decompress(conmon_gz_content)
        conmon_fixed_path = Path('/usr/bin/conmon.fixed')
        conmon_fixed_path.write_bytes(conmon_content)
        conmon_fixed_path.chmod(0o755)
        print('done')
        Path('/usr/bin/conmon').symlink_to('/usr/bin/conmon.fixed')
