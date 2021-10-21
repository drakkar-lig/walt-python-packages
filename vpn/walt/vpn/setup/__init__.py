from plumbum import cli

from walt.common.setup import WaltGenericSetup

SYSTEMD_SERVER_SERVICES = {
    "walt-vpn-server.service": {},
    "walt-vpn-server.socket": {
        'WantedBy': "sockets.target"
    }
}
SYSTEMD_CLIENT_SERVICES = {
    "walt-vpn-client.service": {},
    "walt-vpn-client-setup-credentials.service": {}
}
BUSYBOX_SERVICE_FILES = ["S51waltvpnclient"]


class WalTVPNSetup(WaltGenericSetup):
    package = __name__
    _type = None

    @property
    def display_name(self):
        return "WalT VPN server" if self._type == 'SERVER' else "WalT VPN client"

    def main(self):
        """install WalT VPN software"""
        if self._type == 'SERVER':
            self.setup_systemd_services(SYSTEMD_SERVER_SERVICES)
        elif self._type == 'VPN_CLIENT':

            if self._init_system == "BUSYBOX":
                self.setup_busybox_init_services(BUSYBOX_SERVICE_FILES)
            elif self._init_system == "SYSTEMD":
                self.setup_systemd_services(SYSTEMD_CLIENT_SERVICES)
            else:
                # This is expected to fail and raise correct error message
                self._assert_init_is(("BUSYBOX", "SYSTEMD"))

    @cli.switch("--type", cli.Set('SERVER', 'VPN_CLIENT', case_sensitive=False), mandatory=True)
    def set_type(self, install_type):
        """indicate which kind of setup is requested on this device"""
        self._type = install_type.upper()


def run():
    WalTVPNSetup.run()
