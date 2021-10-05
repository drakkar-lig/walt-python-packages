import shutil
from pathlib import Path

from pkg_resources import resource_filename

from walt.common.tools import failsafe_symlink

SYSTEMD_SERVICES = [ "walt-logs.service" ]
SYSTEMD_DEFAULT_DIR = Path("/etc/systemd/system")


def setup_systemd(systemd_dir: Path = SYSTEMD_DEFAULT_DIR):
    systemd_install_dir = systemd_dir / "multi-user.target.wants"
    for service in SYSTEMD_SERVICES:
        service_path = resource_filename(__name__, service)
        shutil.copy(service_path, systemd_dir)
        # the following is the same as running 'systemctl enable <service>'
        # on a system that is really running
        failsafe_symlink(systemd_dir / service,
                         systemd_install_dir / service)
