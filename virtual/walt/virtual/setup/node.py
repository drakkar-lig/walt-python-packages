from walt.common.setup import WaltGenericSetup

BUSYBOX_SERVICE_FILES = ["S52waltvirtualnode"]


class WalTStandaloneVirtualNodeSetup(WaltGenericSetup):
    package = __name__

    @property
    def display_name(self):
        return "WalT virtual"

    def main(self):
        """setup a standalone virtual node"""
        self.setup_busybox_init_services(BUSYBOX_SERVICE_FILES)


def run():
    WalTStandaloneVirtualNodeSetup.run()
