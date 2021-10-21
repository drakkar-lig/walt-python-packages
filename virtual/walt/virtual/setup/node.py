from walt.common.setup import WaltGenericSetup

SYSTEMD_SERVICES = {
    "walt-virtual-node@.service": {}
}
BUSYBOX_SERVICE_FILES = ["S52waltvirtualnode"]


class WalTStandaloneVirtualNodeSetup(WaltGenericSetup):
    package = __name__

    @property
    def display_name(self):
        return "WalT virtual"

    def main(self):
        """setup a standalone virtual node"""
        if self._init_system == "BUSYBOX":
            self.setup_busybox_init_services(BUSYBOX_SERVICE_FILES)
        elif self._init_system == "SYSTEMD":
            self.setup_systemd_services(SYSTEMD_SERVICES)
        else:
            # This is expected to fail and raise correct error message
            self._assert_init_is(("BUSYBOX", "SYSTEMD"))


def run():
    WalTStandaloneVirtualNodeSetup.run()
