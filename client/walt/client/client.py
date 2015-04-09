#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import rpyc, sys
from plumbum import cli
from walt.common.constants import WALT_SERVER_DAEMON_PORT

SERVER="localhost"
WALT_VERSION = "0.1"

# most of the functionality is provided at the server,
# of course. 
# but the client also offers to the server a small 
# set of features implemented in the following class.
class WaltClientService(rpyc.Service):
    def exposed_write_stdout(self, s):
        sys.stdout.write(s)
        sys.stdout.flush()

    def exposed_write_stderr(self, s):
        sys.stderr.write(s)
        sys.stdout.flush()

class ClientToServerLink:
    def __enter__(self):
        self.conn = rpyc.connect(
                SERVER,
                WALT_SERVER_DAEMON_PORT,
                service = WaltClientService)
        return self.conn.root

    def __exit__(self, type, value, traceback):
        self.conn.close()

class WalT(cli.Application):
    """WalT (wireless testbed) control tool."""
    VERSION = WALT_VERSION

@WalT.subcommand("platform")
class WalTPlatform(cli.Application):
    """platform-management sub-commands"""

@WalTPlatform.subcommand("show")
class WalTPlatformPrint(cli.Application):
    """print a view of the devices involved in the platform"""
    _details = False # default
    def main(self):
        with ClientToServerLink() as server:
            print server.describe(self._details)
    @cli.autoswitch()
    def details(self):
        self._details = True

@WalTPlatform.subcommand("rescan")
class WalTPlatformRescan(cli.Application):
    """rescan the network devices involved in the platform"""
    def main(self):
        with ClientToServerLink() as server:
            server.update()

@WalTPlatform.subcommand("rename-device")
class WalTRenameDevice(cli.Application):
    """rename a device"""
    def main(self, old_name, new_name):
        with ClientToServerLink() as server:
            server.rename(old_name, new_name)

@WalT.subcommand("node")
class WalTNode(cli.Application):
    """node management sub-commands"""

@WalTNode.subcommand("blink")
class WalTNodeBlink(cli.Application):
    """make a node blink for a given number of seconds"""
    def main(self, node_name, duration=60):
        with ClientToServerLink() as server:
            server.blink(node_name, int(duration))

@WalTNode.subcommand("reboot")
class WalTNodeReboot(cli.Application):
    """reboot a node"""
    def main(self, node_name):
        with ClientToServerLink() as server:
            server.reboot(node_name)

@WalT.subcommand("traces")
class WalTTraces(cli.Application):
    """traces-management sub-commands"""
    def main(self, remote, branch = None):
        print "doing the push..."

def run():
    WalT.run()

if __name__ == "__main__":
    run()

