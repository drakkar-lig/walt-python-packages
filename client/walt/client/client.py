#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import rpyc
from plumbum import cli
from walt.common.constants import WALT_SERVER_DAEMON_PORT

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
        conn = rpyc.connect(SERVER, WALT_SERVER_DAEMON_PORT)
        platform_manager = conn.root
        print platform_manager.describe()

@WalTPlatform.subcommand("rescan")
class WalTPlatformRescan(cli.Application):
    """rescan the network devices involved in the platform"""
    def main(self):
        conn = rpyc.connect(SERVER, WALT_SERVER_DAEMON_PORT)
        platform_manager = conn.root
        platform_manager.update()
        print 'done.'

@WalT.subcommand("node")
class WalTNode(cli.Application):
    """node management sub-commands"""

@WalTNode.subcommand("blink")
class WalTNodeBlink(cli.Application):
    """make a node blink for a given number of seconds"""
    def main(self, ip_address, duration=60):
        conn = rpyc.connect(SERVER, WALT_SERVER_DAEMON_PORT)
        platform_manager = conn.root
        platform_manager.blink(ip_address, int(duration))
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

