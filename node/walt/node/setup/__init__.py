from walt.common.setup import WaltGenericSetup


class WaltNodeSetup(WaltGenericSetup):
    package = __name__

    @property
    def display_name(self):
        return "WalT node"

    def main(self):
        """install WalT node software"""
        self.setup_systemd_services(["walt-logs.service"])


def run():
    WaltNodeSetup.run()
