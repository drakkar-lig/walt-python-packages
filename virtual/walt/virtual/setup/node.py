import subprocess
import sys
from pathlib import Path

from pkg_resources import resource_string
from plumbum import cli

BUSYBOX_CLIENT_SERVICE_FILES = [ "S52waltvirtualnode" ]
BUSYBOX_SERVICES_DIR = Path("/etc/init.d")

def setup_virtual_node(init_system, start_services):
    if init_system != 'BUSYBOX':
        sys.exit("Setting up a standalone virtual node with %s init system is not implemented. Exiting." % init_system)
    for filename in BUSYBOX_CLIENT_SERVICE_FILES:
        service_file_content = resource_string(__name__, filename)
        service_file_path = BUSYBOX_SERVICES_DIR / filename
        if service_file_path.exists():
            sys.exit('walt standalone virtual node services are already setup. Exiting.')
        service_file_path.write_bytes(service_file_content)
        service_file_path.chmod(0o755)  # make it executable
        if start_services:
            subprocess.call([ service_file_path, 'start' ])
    print('Done.')

class WalTStandaloneVirtualNodeSetup(cli.Application):
    _init_system = None
    _start = False

    def main(self):
        """setup a standalone virtual node"""
        setup_virtual_node(self._init_system, self._start)

    @cli.switch("--init-system", cli.Set('SYSTEMD', 'BUSYBOX', case_sensitive = False), mandatory = True)
    def set_init_system(self, init_system):
        """indicate the init system available on this device"""
        self._init_system = init_system.upper()

    @cli.switch("--start")
    def set_start(self):
        """start services once installed"""
        self._start = True

def run():
    WalTStandaloneVirtualNodeSetup.run()
