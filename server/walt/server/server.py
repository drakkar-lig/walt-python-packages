#!/usr/bin/env python

import rpyc, sys, logging
from plumbum import cli
from walt.server.rpycserver import SimpleRPyCServer
from walt.server.platform import PoEPlatform

WALT_SERVER_VERSION = 0.1

class PlatformService(rpyc.Service):
    ALIASES=("WalT_Platform",)
    def __init__(self, *args, **kwargs):
        rpyc.Service.__init__(self, *args, **kwargs)

    def exposed_update(self):
        PlatformService.platform.update()

    def exposed_describe(self):
        return PlatformService.platform.describe()


class WalTServer(cli.Application):
    """WalT (wireless testbed) server software."""
    VERSION = WALT_SERVER_VERSION

    def __init__(self, *args, **kwargs):
        cli.Application.__init__(self, *args, **kwargs)
        self.loglevel = logging.WARNING

    @cli.switch("--log", str)
    def set_log_level(self, loglevel):
        """Sets the log-level of the logger"""
        numeric_level = getattr(logging, loglevel.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % loglevel)
        self.loglevel = numeric_level

    def main(self):
        sys.stdout.write("Initializing... ")
        sys.stdout.flush()
        logging.basicConfig(level=self.loglevel)
        PlatformService.platform = PoEPlatform()
        server = SimpleRPyCServer(PlatformService, port = 12345)
        print("Done.")  # end of initialization
        try:
            server.start()
        except KeyboardInterrupt:
            print 'Interrupted.'

def run():
    WalTServer.run()

if __name__ == "__main__":
    run()

