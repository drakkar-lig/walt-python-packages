#!/usr/bin/env python
import os, sys
from walt.common.tools import failsafe_symlink
from pkg_resources import resource_string
from pathlib import Path
from plumbum import cli

SYSTEMD_SERVER_SERVICE_FILES = [ "walt-vpn-server.service", "walt-vpn-server.socket" ]
SYSTEMD_SERVICES_DIR = Path("/etc/systemd/system")

BUSYBOX_VPN_CLIENT_SERVICE_FILES = [ "S51waltvpnclient", "S52waltvirtualnode" ]
BUSYBOX_SERVICES_DIR = Path("/etc/init.d")

def setup_server(init_system, start_services):
    if start_services:
        print('Note: flag --start was ignored. walt-vpn-server service is automatically started on client connection.')
    if init_system != 'SYSTEMD':
        sys.exit("Setting up a server with %s init system is not implemented. Exiting." % init_system)
    if os.geteuid() != 0:
        sys.exit("This script must be run as root. Exiting.")
    for filename in SYSTEMD_SERVER_SERVICE_FILES:
        service_file_content = resource_string(__name__, filename)
        service_file_path = SYSTEMD_SERVICES_DIR / filename
        if service_file_path.exists():
            sys.exit('walt-virtual services are already setup. Exiting.')
        service_file_path.write_bytes(service_file_content)
        if filename.endswith('.socket'):
            # the following is the same as running 'systemctl enable <unit>.socket'
            # on a system that is really running
            failsafe_symlink(str(service_file_path),
                             str(SYSTEMD_SERVICES_DIR / "sockets.target.wants" / filename))
    print('Done.')

def setup_vpn_client(init_system, start_services):
    if init_system != 'BUSYBOX':
        sys.exit("Setting up a vpn client with %s init system is not implemented. Exiting." % init_system)
    for filename in BUSYBOX_VPN_CLIENT_SERVICE_FILES:
        service_file_content = resource_string(__name__, filename)
        service_file_path = BUSYBOX_SERVICES_DIR / filename
        if service_file_path.exists():
            sys.exit('walt-virtual services are already setup. Exiting.')
        service_file_path.write_bytes(service_file_content)
        service_file_path.chmod(0o755)  # make it executable
        if start_services:
            subprocess.call([ service_file_path, 'start' ])
    print('Done.')

def setup(info):
    if info._type == 'SERVER':
        setup_server(info._init_system, info._start)
    elif info._type == 'VPN_CLIENT':
        setup_vpn_client(info._init_system, info._start)

class WalTVirtualSetup(cli.Application):
    _type = None
    _init_system = None
    _start = False

    def main(self):
        """install walt-virtual software"""
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

def run():
    WalTVirtualSetup.run()
