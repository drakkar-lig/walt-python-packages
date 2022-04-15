import sys, subprocess
from plumbum import cli
from pathlib import Path
from walt.common import systemd
from walt.common.setup import WaltGenericSetup
from walt.common.tools import verify_root_login_shell
from walt.server.setup.ossetup import get_os_codename, upgrade_os, install_os, fix_os, install_os_on_image
from walt.server.setup.conf import fix_other_conf_files, setup_default_server_conf, ask_server_conf

WALT_SERVICES = [
    "walt-server.service",
    "walt-server-netconfig.service",
    "walt-server-dhcpd.service",
    "walt-server-tftpd.service",
    "walt-server-snmpd.service",
    "walt-server-lldpd.service",
    "walt-server-ptpd.service",
    "walt-server-httpd.service"
]

# WALT has its own version of the following services.
# Since in their default configuration they would conflict with these
# walt services, we have to disable them.
UNCOMPATIBLE_OS_SERVICES = [
    'tftpd-hpa.service', 'isc-dhcp-server.service', 'snmpd.service', 'lldpd.service', 'ptpd.service'
]

WALT_MAIN_SERVICE = 'walt-server.service'

OS_ACTIONS = {
    'image-install': {
        'bullseye': ('install_os_on_image', 'disable_os_services', 'setup_walt_services',
                     'fix_other_conf_files', 'setup_default_server_conf', 'update_completion'),
    },
    'install': {
        'bullseye': ('install_os', 'disable_os_services', 'setup_walt_services',
                     'fix_other_conf_files', 'ask_server_conf', 'systemd_reload',
                     'start_walt_services', 'update_completion', 'msg_ready'),
    },
    'upgrade': {
        'buster': ('stop_services', 'upgrade_os', 'disable_os_services', 'setup_walt_services',
                   'fix_other_conf_files', 'update_completion', 'msg_reboot'),
        'bullseye': ('stop_services', 'fix_os', 'disable_os_services', 'setup_walt_services',
                     'fix_other_conf_files', 'may_ask_server_conf', 'systemd_reload', 'start_walt_services',
                     'update_completion', 'msg_ready'),
    }
}

WALT_BASH_COMPLETION_PATH = Path('/etc/bash_completion.d/walt')

class WalTServerSetup(WaltGenericSetup):
    package = __name__
    mode = cli.SwitchAttr(
                "--mode",
                cli.Set("AUTO", "INSTALL", "UPGRADE", "IMAGE-INSTALL", case_sensitive=False),
                argname = 'SETUP_MODE',
                default = 'auto',
                help= """specify mode (if unsure, leave unspecified!)""")
    opt_edit_conf = cli.Flag(
                "--edit-conf",
                default = False,
                help= """edit server configuration""")

    @property
    def display_name(self):
        return "WalT server"

    def main(self):
        """setup WalT server"""
        verify_root_login_shell()
        os_codename = get_os_codename()
        if self.mode.lower() == 'auto':
            if self.systemd_unit_exists('walt-server.service'):
                mode = 'upgrade'
            else:
                mode = 'install'
        else:
            mode = self.mode.lower()
        if os_codename not in OS_ACTIONS[mode]:
            allowed = ', '.join(OS_ACTIONS[mode].keys())
            print(f'Sorry, {mode} mode of this script only works on the following debian version(s): {allowed}.')
            print('Exiting.')
            sys.exit(1)
        for action in OS_ACTIONS[mode][os_codename]:
            method = getattr(self, action)
            method()

    def msg_reboot(self):
        print('** You must now reboot the machine. **')

    def msg_ready(self):
        print('** Your WalT server is ready. **')

    def systemd_reload(self):
        print('Reloading systemd... ', end=''); sys.stdout.flush()
        systemd.reload()
        print('done')

    def stop_services(self):
        print('Ensuring OS services related to WalT are stopped... ', end=''); sys.stdout.flush()
        to_be_stopped = list(UNCOMPATIBLE_OS_SERVICES)
        # previous versions of walt had fewer walt services
        for walt_unit in WALT_SERVICES:
            if self.systemd_unit_exists(walt_unit):
                to_be_stopped.append(walt_unit)
        self.stop_systemd_services(to_be_stopped)
        print('done')

    def start_walt_services(self):
        print('Restarting WalT services... ', end=''); sys.stdout.flush()
        # starting main service is enough to start all, thanks to dependencies
        self.start_systemd_services([WALT_MAIN_SERVICE])
        print('done')

    def disable_os_services(self):
        print('Ensuring OS services incompatible with WalT are disabled... ', end=''); sys.stdout.flush()
        # remove file /etc/systemd/system/isc-dhcp-server.service which was historically added
        # to fine tune the service better than using the service file auto-generated for the
        # SYSV service
        dhcp_service = Path('/etc/systemd/system/isc-dhcp-server.service')
        if dhcp_service.exists():
            dhcp_service.unlink()
            dhcp_service_symlink = Path('/etc/systemd/system/multi-user.wants/isc-dhcp-server.service')
            if dhcp_service_symlink.exists():
                dhcp_service_symlink.unlink()
        self.disable_systemd_services(UNCOMPATIBLE_OS_SERVICES)
        print('done')

    def upgrade_os(self):
        upgrade_os()

    def install_os(self):
        install_os()

    def fix_os(self):
        fix_os()

    def install_os_on_image(self):
        install_os_on_image()

    def setup_walt_services(self):
        print('Ensuring WalT services are properly registered on the OS... ', end=''); sys.stdout.flush()
        self.setup_systemd_services(WALT_SERVICES)
        subprocess.run('walt-vpn-setup --type SERVER'.split(), check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print('done')

    def setup_default_server_conf(self):
        setup_default_server_conf()

    def fix_other_conf_files(self):
        fix_other_conf_files()

    def ask_server_conf(self):
        ask_server_conf()

    def may_ask_server_conf(self):
        if self.opt_edit_conf:
            ask_server_conf()

    def update_completion(self):
        print('Updating bash completion for walt tool... ', end=''); sys.stdout.flush()
        p = subprocess.run('walt advanced dump-bash-autocomplete'.split(),
                           check=True, stdout=subprocess.PIPE)
        WALT_BASH_COMPLETION_PATH.parent.mkdir(parents=True, exist_ok=True)
        WALT_BASH_COMPLETION_PATH.write_bytes(p.stdout)
        print('done')


def run():
    WalTServerSetup.run()