from importlib.resources import files
from walt.common.setup import WaltGenericSetup

BUSYBOX_SERVICE_FILES = ["S52waltvirtualnode"]


class WalTStandaloneVirtualNodeSetup(WaltGenericSetup):

    @property
    def package(self):
        import walt.virtual.setup
        return files(walt.virtual.setup)

    @property
    def display_name(self):
        return "WalT virtual"

    def main(self):
        """setup a standalone virtual node"""
        self.setup_busybox_init_services(BUSYBOX_SERVICE_FILES)


def run():
    WalTStandaloneVirtualNodeSetup.run()
