import os, sys
from walt.common.tools import failsafe_symlink
from pkg_resources import resource_string
from pathlib import Path

SYSTEMD_SERVICES_DEF = {
            "walt-server.service": None,
            "walt-server-httpd.service": 'walt-server.service'
}
SYSTEMD_SERVICES_DIR = Path("/etc/systemd/system")

def run():
    if os.geteuid() != 0:
        sys.exit("This script must be run as root. Exiting.")
    for service, wanted_by in SYSTEMD_SERVICES_DEF.items():
        service_file_content = resource_string(__name__, service)
        service_file_path = SYSTEMD_SERVICES_DIR / service
        if service_file_path.exists():
            print('Overwriting ' + str(service_file_path))
        service_file_path.write_bytes(service_file_content)
        if wanted_by is not None:
            # the following is the same as running 'systemctl enable <service>'
            # on a system that is really running
            failsafe_symlink(str(service_file_path),
                             str(SYSTEMD_SERVICES_DIR / \
                                 (wanted_by + '.wants') / service))
    print('Done.')
