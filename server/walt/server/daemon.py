#!/usr/bin/env python

import rpyc
from walt.common.daemon import WalTDaemon
from walt.server.topology import PoEPlatform
from walt.common.constants import           \
                 WALT_SERVER_DAEMON_PORT,   \
                 WALT_NODE_DAEMON_PORT

WALT_SERVER_DAEMON_VERSION = 0.1

class PlatformService(rpyc.Service):
    ALIASES=("WalT_Platform",)
    def __init__(self, *args, **kwargs):
        rpyc.Service.__init__(self, *args, **kwargs)

    def exposed_update(self):
        PlatformService.platform.update()

    def exposed_describe(self):
        return PlatformService.platform.describe()

    def exposed_blink(self, ip_address, duration):
        conn = rpyc.connect(ip_address, WALT_NODE_DAEMON_PORT)
        node_service = conn.root
        node_service.blink(duration)


class WalTServerDaemon(WalTDaemon):
    """WalT (wireless testbed) server daemon."""
    VERSION = WALT_SERVER_DAEMON_VERSION

    def getRPyCServiceClassAndPort(self):
        return (PlatformService, WALT_SERVER_DAEMON_PORT)

    def init(self):
        print "init"
        PlatformService.platform = PoEPlatform()

def run():
    WalTServerDaemon.run()

if __name__ == "__main__":
    run()

