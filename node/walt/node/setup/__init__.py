from walt.common.setup import WaltGenericSetup

SYSTEMD_SERVICES = {
    "walt-logs.service": {
        'WantedBy': "multi-user.target"
    }
}


class WaltNodeSetup(WaltGenericSetup):
    package = __name__

    @property
    def display_name(self):
        return "WalT node"

    def main(self):
        """install WalT node software"""
        self.setup_systemd_services(SYSTEMD_SERVICES)


def run():
    WaltNodeSetup.run()
