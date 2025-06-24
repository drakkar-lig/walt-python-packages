import shlex
import subprocess
import sys
from pathlib import Path

from importlib.resources import files
from plumbum import cli
from walt.common import systemd
from walt.common.setup import WaltGenericSetup
from walt.common.tools import verify_root_login_shell
from walt.server.setup.conf import (
    define_server_conf,
    fix_other_conf_files,
    update_server_conf,
)
from walt.server.setup.ossetup import (
    cleanup_old_walt_install,
    fix_conmon,
    fix_os,
    get_os_codename,
    install_os,
    install_os_on_image,
    record_start_os_upgrade,
    record_end_os_upgrade,
    upgrade_os,
)
from walt.server.setup.vpn import setup_vpn

STOPPABLE_WALT_SERVICES = [
    "walt-server.service",
    "walt-server-dhcpd.service",
    "walt-server-named.service",
    "walt-server-tftpd.service",
    "walt-server-snmpd.service",
    "walt-server-lldpd.service",
    "walt-server-ptpd.service",
    "walt-server-httpd.service",
    "walt-server-nbd.service",
    "walt-server-nbd.socket",
    "walt-server-podman.service",
    "walt-server-podman.socket",
    "walt-server-vpn.service",
    "walt-server-vpn.socket",
]

# The user may have configured the interface providing internet access
# in walt server conf file, so if we stop walt-server-netconfig, next
# operations (apt packages upgrade) may fail. We will keep it running
# instead and just restart it at the end of the upgrade.
RESTARTABLE_WALT_SERVICES = [
    "walt-server-netconfig.service",
]

# The following are obsolete walt services (or they were renamed)
OBSOLETE_WALT_SERVICES = [
    "walt-vpn-server.service",
    "walt-vpn-server.socket",
]

# all walt services
ALL_WALT_SERVICES = STOPPABLE_WALT_SERVICES + RESTARTABLE_WALT_SERVICES

# WALT has its own version of the following services.
# Since in their default configuration they would conflict with these
# walt services, we have to disable them.
UNCOMPATIBLE_OS_SERVICES = [
    "tftpd-hpa.service",
    "isc-dhcp-server.service",
    "named.service",
    "snmpd.service",
    "lldpd.service",
    "ptpd.service",
]

WALT_SOCKET_SERVICES = ["walt-server-podman.socket",
                        "walt-server-nbd.socket",
                        "walt-server-vpn.socket"]
WALT_MAIN_SERVICE = "walt-server.service"

# Notes:
# * when the user changes the SSH VPN entrypoint in the interactive
#   configuration screen ("define_server_conf" step), the value
#   is checked by trying an SSH connection. This requires the SSH
#   CA keys to be ready, so the "setup_vpn" step should have been
#   called already.
# * when the user changes the HTTP VPN entrypoint in the interactive
#   configuration screen ("define_server_conf" step), the value
#   is checked by trying an HTTP connection and concurrently waiting
#   for the proxy to connect to this server. This requires port 80
#   to be free, so "stop_services" should have been called already.
OS_ACTIONS = {
    "image-install": {
        "bookworm": (
            "setup_vpn",
            "define_server_conf",
            "install_os_on_image",
            "fix_conmon",
            "disable_os_services",
            "setup_command_symlinks",
            "setup_walt_services",
            "fix_other_conf_files",
            "update_server_conf",
            "update_completion",
        ),
    },
    "install": {
        "bookworm": (
            "stop_services",
            "setup_vpn",
            "define_server_conf",
            "install_os",
            "fix_conmon",
            "disable_os_services",
            "setup_command_symlinks",
            "setup_walt_services",
            "fix_other_conf_files",
            "update_server_conf",
            "systemd_reload",
            "start_walt_services",
            "update_completion",
            "msg_ready",
        ),
    },
    "upgrade": {
        "bullseye": (
            "record_start_os_upgrade",
            "stop_services",
            "setup_vpn",
            "define_server_conf",
            "upgrade_os",
            "fix_conmon",
            "disable_os_services",
            "remove_obsolete_services",
            "cleanup_old_walt_install",
            "setup_command_symlinks",
            "setup_walt_services",
            "fix_other_conf_files",
            "update_server_conf",
            "update_completion",
            "record_end_os_upgrade",
            "msg_reboot",
        ),
        "bookworm": (
            "stop_services",
            "setup_vpn",
            "define_server_conf",
            "fix_os",
            "fix_conmon",
            "disable_os_services",
            "remove_obsolete_services",
            "cleanup_old_walt_install",
            "setup_command_symlinks",
            "setup_walt_services",
            "fix_other_conf_files",
            "update_server_conf",
            "systemd_reload",
            "start_walt_services",
            "update_completion",
            "msg_ready",
        ),
    },
}

WALT_BASH_COMPLETION_PATH = Path("/etc/bash_completion.d/walt")
WALT_ZSH_COMPLETION_PATH = Path("/usr/local/share/zsh/site-functions/_walt")

APPARMOR_CONFS = {
        "usr.sbin.dhcpd": """
/var/lib/walt/services/dhcpd/*.conf r,
/var/lib/walt/services/dhcpd/*.leases* lrw,
/run/walt/dhcpd/dhcpd.pid rw,
/root/walt-*/.venv/bin/walt-dhcp-event ux,  # developer setups
/opt/walt-*/bin/walt-dhcp-event ux,         # prod setups
""",
        "usr.sbin.named": """
/var/lib/walt/services/named/*.conf r,
/var/lib/walt/services/named/*.zone r,
/var/lib/walt/services/named/tmp* rw,
/var/lib/walt/services/named/managed-keys.* rw,
/run/walt/named/named.pid rw,
""",
}


class WalTServerSetup(WaltGenericSetup):
    mode = cli.SwitchAttr(
        "--mode",
        cli.Set("AUTO", "INSTALL", "UPGRADE", "IMAGE-INSTALL", case_sensitive=False),
        argname="SETUP_MODE",
        default="auto",
        help="""specify mode (if unsure, leave unspecified!)""",
    )
    opt_edit_conf = cli.Flag(
        "--edit-conf", default=False, help="""edit server configuration"""
    )

    @property
    def package(self):
        import walt.server.setup
        return files(walt.server.setup)

    @property
    def display_name(self):
        return "WalT server"

    def main(self):
        """setup WalT server"""
        assert (
            Path(sys.prefix) / "bin" / "activate"
        ).exists(), "walt-server seems not installed in a virtual environment"
        verify_root_login_shell()
        os_codename = get_os_codename()
        if self.mode.lower() == "auto":
            if self.systemd_unit_exists("walt-server.service"):
                mode = "upgrade"
            else:
                mode = "install"
        else:
            mode = self.mode.lower()
        if os_codename not in OS_ACTIONS[mode]:
            allowed = ", ".join(OS_ACTIONS[mode].keys())
            print(
                f"Sorry, {mode} mode of this script only works on the following debian"
                f" version(s): {allowed}."
            )
            print("Exiting.")
            sys.exit(1)
        self.resolved_mode = mode
        for action in OS_ACTIONS[mode][os_codename]:
            method = getattr(self, action)
            method()

    def msg_reboot(self):
        print("** You must now reboot the machine. **")

    def msg_ready(self):
        print("** Your WalT server is ready. **")

    def setup_vpn(self):
        setup_vpn()

    def systemd_reload(self):
        print("Reloading systemd... ", end="")
        sys.stdout.flush()
        systemd.reload()
        print("done")

    def stop_services(self):
        print("Ensuring OS services related to WalT are stopped... ", end="")
        sys.stdout.flush()
        to_be_stopped = list(UNCOMPATIBLE_OS_SERVICES)
        # previous versions of walt had fewer walt services
        for walt_unit in STOPPABLE_WALT_SERVICES + OBSOLETE_WALT_SERVICES:
            if self.systemd_unit_exists(walt_unit):
                to_be_stopped.append(walt_unit)
        self.stop_systemd_services(to_be_stopped)
        print("done")

    def start_walt_services(self):
        print("Restarting WalT services... ", end="")
        sys.stdout.flush()
        # restart some services which may have been updated
        self.restart_systemd_services(RESTARTABLE_WALT_SERVICES)
        # starting socket services and main service is enough to start all, thanks
        # to dependencies.
        self.start_systemd_services(WALT_SOCKET_SERVICES + [WALT_MAIN_SERVICE])
        print("done")

    def disable_os_services(self):
        print("Ensuring OS services incompatible with WalT are disabled... ", end="")
        sys.stdout.flush()
        # remove file /etc/systemd/system/isc-dhcp-server.service which was historically
        # added to fine tune the service better than using the service file
        # auto-generated for the SYSV service
        dhcp_service = Path("/etc/systemd/system/isc-dhcp-server.service")
        if dhcp_service.exists():
            dhcp_service.unlink()
            dhcp_service_symlink = Path(
                "/etc/systemd/system/multi-user.wants/isc-dhcp-server.service"
            )
            if dhcp_service_symlink.is_symlink():
                dhcp_service_symlink.unlink()
        self.disable_systemd_services(UNCOMPATIBLE_OS_SERVICES)
        print("done")

    def remove_obsolete_services(self):
        print("Removing any obsolete WalT services... ", end="")
        sys.stdout.flush()
        to_be_removed = []
        for walt_unit in OBSOLETE_WALT_SERVICES:
            if self.systemd_unit_exists(walt_unit):
                to_be_removed.append(walt_unit)
        self.disable_systemd_services(to_be_removed)
        for walt_unit in to_be_removed:
            Path(f"/etc/systemd/system/{walt_unit}").unlink()
        print("done")

    def record_start_os_upgrade(self):
        record_start_os_upgrade()

    def record_end_os_upgrade(self):
        record_end_os_upgrade()

    def upgrade_os(self):
        upgrade_os()

    def install_os(self):
        install_os()

    def fix_os(self):
        fix_os()

    def fix_conmon(self):
        fix_conmon()

    def install_os_on_image(self):
        install_os_on_image()

    def setup_walt_services(self):
        print("Ensuring WalT services are properly registered on the OS... ", end="")
        sys.stdout.flush()
        self.setup_systemd_services(ALL_WALT_SERVICES)
        self.setup_apparmor_profiles()
        print("done")

    def setup_apparmor_profiles(self):
        for apparmor_file, apparmor_conf in APPARMOR_CONFS.items():
            p = Path("/etc/apparmor.d/local/") / apparmor_file
            if not p.exists() or p.read_text() != apparmor_conf:
                p.write_text(apparmor_conf)
                # reload the profile
                subprocess.run(shlex.split(
                    f"apparmor_parser -r /etc/apparmor.d/{apparmor_file}"))

    def cleanup_old_walt_install(self):
        cleanup_old_walt_install()

    def fix_other_conf_files(self):
        fix_other_conf_files()

    # note: when the interactive conf editor must be started, it is more user-friendly
    # to start it first than in the middle of possibly long install/upgrade steps.
    # so define_server_conf() is called as a first step, but the resulting configuration
    # will be applied later, when appropriate, by the call to update_server_conf().
    def define_server_conf(self):
        self.server_conf = define_server_conf(self.resolved_mode, self.opt_edit_conf)

    def update_server_conf(self):
        update_server_conf(self.server_conf)

    def update_completion(self):
        print("Updating bash & zsh completion for walt tool... ", end="")
        sys.stdout.flush()
        for shell, path in (("bash", WALT_BASH_COMPLETION_PATH),
                            ("zsh", WALT_ZSH_COMPLETION_PATH)):
            p = subprocess.run(
                f"walt advanced dump-{shell}-autocomplete".split(),
                check=True,
                stdout=subprocess.PIPE,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(p.stdout)
        print("done")


def run():
    WalTServerSetup.run()
