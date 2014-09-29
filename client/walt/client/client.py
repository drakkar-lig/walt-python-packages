#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import rpyc
from plumbum import cli

SERVER="localhost"
WALT_VERSION = "0.1"

class WalT(cli.Application):
    """WalT (wireless testbed) control tool."""
    VERSION = WALT_VERSION

@WalT.subcommand("platform")
class WalTPlatform(cli.Application):
    """platform-management sub-commands"""

@WalTPlatform.subcommand("print")
class WalTPlatformPrint(cli.Application):
    """print a view of the devices involved in the platform"""
    def main(self):
        conn = rpyc.connect(SERVER, 12345)
        platform_manager = conn.root
        print platform_manager.describe()

@WalTPlatform.subcommand("rescan")
class WalTPlatformRescan(cli.Application):
    """rescan the network devices involved in the platform"""
    def main(self):
        conn = rpyc.connect(SERVER, 12345)
        platform_manager = conn.root
        platform_manager.update()
        print 'done.'

@WalT.subcommand("traces")
class WalTTraces(cli.Application):
    """traces-management sub-commands"""
    def main(self, remote, branch = None):
        print "doing the push..."

def run():
    WalT.run()

if __name__ == "__main__":
    run()

