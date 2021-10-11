from walt.common.setup import WaltGenericSetup

SYSTEMD_SERVICES = {
    "walt-server.service": {},
    "walt-server-netconfig.service": {},
    "walt-server-dhcpd.service": {
        'WantedBy': "walt-server-netconfig.service"
    },
    "walt-server-httpd.service": {
        'WantedBy': "walt-server.service"
    }
}


class WalTServerSetup(WaltGenericSetup):
    package = __name__

    @property
    def display_name(self):
        return "WalT server"

    def main(self):
        """install WalT server software"""
        self.setup_systemd_services(SYSTEMD_SERVICES)


def run():
    WalTServerSetup.run()
