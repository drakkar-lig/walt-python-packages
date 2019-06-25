#!/usr/bin/env python
import os, sys
from walt.common.tools import failsafe_symlink
from pkg_resources import resource_string
from pathlib import Path

SYSTEMD_SERVICE_FILES = [ "walt-vpn-server.service", "walt-vpn-server.socket" ]
SYSTEMD_SERVICES_DIR = Path("/etc/systemd/system")

def run():
    if os.geteuid() != 0:
        sys.exit("This script must be run as root. Exiting.")
    for filename in SYSTEMD_SERVICE_FILES:
        service_file_content = resource_string(__name__, filename)
        service_file_path = SYSTEMD_SERVICES_DIR / filename
        if service_file_path.exists():
            sys.exit('Virtual tools are already setup. Exiting.')
        service_file_path.write_bytes(service_file_content)
        if filename.endswith('.socket'):
            # the following is the same as running 'systemctl enable <unit>.socket'
            # on a system that is really running
            failsafe_symlink(str(service_file_path),
                             str(SYSTEMD_SERVICES_DIR / "sockets.target.wants" / filename))
    print('Done.')
