#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import readline
from plumbum import cli
from walt.common.logs import LogsConnectionToServer
from walt.client.link import ClientToServerLink

SERVER="localhost"
WALT_VERSION = "0.1"
DEFAULT_FORMAT_STRING= \
   '{timestamp:%H:%M:%S.%f} {sender}.{stream} -> {line}'

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

@WalTNode.subcommand("list")
class WalTNodeList(cli.Application):
    """list available WalT nodes"""
    def main(self):
        with ClientToServerLink() as server:
            print server.list_nodes()

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

@WalTNode.subcommand("set-image")
class WalTNodeSetImage(cli.Application):
    """associate an operating system image to a node"""
    def main(self, node_name, image_name):
        with ClientToServerLink() as server:
            server.set_image(node_name, image_name)

@WalT.subcommand("image")
class WalTImage(cli.Application):
    """Sub-commands related to WalT-nodes operating system images"""

@WalTImage.subcommand("list")
class WalTImageList(cli.Application):
    """list available WalT node OS images"""
    def main(self):
        with ClientToServerLink() as server:
            print server.list_images()

@WalTImage.subcommand("set-default")
class WalTImageSetDefault(cli.Application):
    """set the default image to be booted when a node connects
       to the server for the first time"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            server.set_default_image(image_name)

@WalT.subcommand("logs")
class WalTLogs(cli.Application):
    """logs-management sub-commands"""

@WalTLogs.subcommand("show")
class WalTLogsShow(cli.Application):
    """Dump logs on standard output"""
    format_string = cli.SwitchAttr(
                "--format",
                str,
                default = DEFAULT_FORMAT_STRING,
                help= """Specify the python format string used to print log records""")

    def main(self):
        conn = LogsConnectionToServer(SERVER)
        conn.request_log_dump()
        while True:
            try:
                record = conn.read_log_record()
                if record == None:
                    break
                print self.format_string.format(**record)
            except KeyboardInterrupt:
                print
                break
            except Exception as e:
                print 'Could not display the log record.'
                print 'Verify your format string.'
                break

@WalT.subcommand("advanced")
class WalTAdvanced(cli.Application):
    """advanced sub-commands"""

@WalTAdvanced.subcommand("sql")
class WalTAdvancedSql(cli.Application):
    """Start a remote SQL prompt on the Walt server database"""
    def main(self):
        link = ClientToServerLink(True)
        with link as server:
            link.sql_prompt()

def run():
    WalT.run()

if __name__ == "__main__":
    run()

