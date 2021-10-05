import os
import subprocess
import sys
from pathlib import Path

from pkg_resources import resource_string
from plumbum import cli

from walt.common.tools import failsafe_symlink

SYSTEMD_SERVER_SERVICE_FILES = [ "walt-vpn-server.service", "walt-vpn-server.socket" ]
SYSTEMD_DEFAULT_DIR = Path("/etc/systemd/system")

BUSYBOX_VPN_CLIENT_SERVICE_FILES = [ "S51waltvpnclient" ]
BUSYBOX_SERVICES_DIR = Path("/etc/init.d")

def setup_server(init_system, start_services, systemd_dir):
    if start_services:
        print('Note: flag --start was ignored. walt-vpn-server service is automatically started on client connection.')
    if init_system != 'SYSTEMD':
        sys.exit("Setting up a VPN server with %s init system is not implemented. Exiting." % init_system)
    if os.geteuid() != 0:
        sys.exit("This script must be run as root. Exiting.")
    for filename in SYSTEMD_SERVER_SERVICE_FILES:
        service_file_content = resource_string(__name__, filename)
        service_file_path = systemd_dir / filename
        if service_file_path.exists():
            sys.exit('walt vpn services are already setup. Exiting.')
        service_file_path.write_bytes(service_file_content)
        if filename.endswith('.socket'):
            # the following is the same as running 'systemctl enable <unit>.socket'
            # on a system that is really running
            failsafe_symlink(str(service_file_path),
                             str(systemd_dir / "sockets.target.wants" / filename))
    print('Done.')

def setup_vpn_client(init_system, start_services):
    if init_system != 'BUSYBOX':
        sys.exit("Setting up a vpn client with %s init system is not implemented. Exiting." % init_system)
    for filename in BUSYBOX_VPN_CLIENT_SERVICE_FILES:
        service_file_content = resource_string(__name__, filename)
        service_file_path = BUSYBOX_SERVICES_DIR / filename
        if service_file_path.exists():
            sys.exit('walt vpn services are already setup. Exiting.')
        service_file_path.write_bytes(service_file_content)
        service_file_path.chmod(0o755)  # make it executable
        if start_services:
            subprocess.call([ service_file_path, 'start' ])
    print('Done.')

def setup(info):
    if info._type == 'SERVER':
        setup_server(info._init_system, info._start, info.systemd_dir)
    elif info._type == 'VPN_CLIENT':
        setup_vpn_client(info._init_system, info._start)

class WalTVPNSetup(cli.Application):
    _type = None
    _init_system = None
    _start = False
    systemd_dir = SYSTEMD_DEFAULT_DIR

    def main(self):
        """install WALT VPN software"""
        setup(self)

    @cli.switch("--type", cli.Set('SERVER', 'VPN_CLIENT', case_sensitive = False), mandatory = True)
    def set_type(self, install_type):
        """indicate which kind of setup is requested on this device"""
        self._type = install_type.upper()

    @cli.switch("--init-system", cli.Set('SYSTEMD', 'BUSYBOX', case_sensitive = False), mandatory = True)
    def set_init_system(self, init_system):
        """indicate the init system available on this device"""
        self._init_system = init_system.upper()

    @cli.switch("--start")
    def set_start(self):
        """start services once installed"""
        self._start = True

    @cli.switch("--systemd-dir", Path)
    def set_systemd_dir(self, systemd_dir):
        """directory where to store systemd services"""
        self.systemd_dir = systemd_dir

def run():
    WalTVPNSetup.run()
