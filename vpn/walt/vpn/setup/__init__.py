from plumbum import cli
from walt.common.setup import WaltGenericSetup
from walt.common.tools import verify_root_login_shell
from walt.vpn.setup.user import setup_user

SYSTEMD_SERVICES = ["walt-vpn-server.service", "walt-vpn-server.socket"]
BUSYBOX_SERVICE_FILES = ["S51waltvpnclient"]


class WalTVPNSetup(WaltGenericSetup):
    package = __name__
    _type = None

    @property
    def display_name(self):
        return "WalT VPN server" if self._type == "SERVER" else "WalT VPN client"

    def main(self):
        """install WalT VPN software"""
        verify_root_login_shell()
        if self._type == "SERVER":
            setup_user()
            self.setup_systemd_services(SYSTEMD_SERVICES)
        elif self._type == "VPN_CLIENT":
            self.setup_busybox_init_services(BUSYBOX_SERVICE_FILES)

    @cli.switch(
        "--type", cli.Set("SERVER", "VPN_CLIENT", case_sensitive=False), mandatory=True
    )
    def set_type(self, install_type):
        """indicate which kind of setup is requested on this device"""
        self._type = install_type.upper()


def run():
    WalTVPNSetup.run()
