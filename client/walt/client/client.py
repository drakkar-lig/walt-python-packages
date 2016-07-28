#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import sys, socket
from plumbum import cli
from walt.client import myhelp
from walt.client.log import WalTLog
from walt.client.advanced import WalTAdvanced
from walt.client.node import WalTNode
from walt.client.device import WalTDevice
from walt.client.image import WalTImage
from walt.client.startup import init_config
from walt.common.versions import UPLOAD
from walt.client.update import client_update
from walt.client.tools import restart

class WalT(cli.Application):
    """WalT (wireless testbed) control tool."""
    VERSION = 'client v' + str(UPLOAD)

    @cli.switch(["-z", "--help-about"], str,
                group = "Meta-switches")
    def help_about(self, topic):
        """Prints help details about a given topic.
           Run 'walt --help-about help' to list them.
        """
        print myhelp.get(topic)
        sys.exit()

WalT.subcommand("advanced", WalTAdvanced)
WalT.subcommand("device", WalTDevice)
WalT.subcommand("image", WalTImage)
WalT.subcommand("log", WalTLog)
WalT.subcommand("node", WalTNode)

def run():
    init_config()
    try:
        if client_update():
            restart()   # this will never return, no need to exit
        WalT.run()
    except socket.error:
        print 'Network connection to WalT server failed.'

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print
        print 'Aborted.'

