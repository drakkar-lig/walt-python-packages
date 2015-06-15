#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import readline, time
from plumbum import cli
from walt.common.logs import LogsConnectionToServer
from walt.client.link import ClientToServerLink
from walt.client.config import conf
from walt.client.interactive import run_sql_prompt, \
                                    run_modify_image_prompt

WALT_VERSION = "0.1"
DEFAULT_FORMAT_STRING= \
   '{timestamp:%H:%M:%S.%f} {sender}.{stream} -> {line}'
POE_REBOOT_DELAY            = 2  # seconds

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
            if server.poweroff(node_name):
                print node_name, 'was powered off.'
                time.sleep(POE_REBOOT_DELAY)
                server.poweron(node_name)
                print node_name, 'was powered on.'

@WalTNode.subcommand("deploy")
class WalTNodeDeploy(cli.Application):
    """deploy an operating system image on a node"""
    def main(self, node_name, image_name):
        with ClientToServerLink() as server:
            if server.has_image(image_name):
                if server.poweroff(node_name):
                    print node_name, 'was powered off.'
                    server.set_image(node_name, image_name)
                    time.sleep(POE_REBOOT_DELAY)
                    print '%s will now boot %s.' % \
                                (node_name, image_name)
                    server.poweron(node_name)
                    print node_name, 'was powered on.'

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

@WalTImage.subcommand("modify")
class WalTImageModify(cli.Application):
    """run an interactive shell allowing to modify a given
       image"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            session = server.create_modify_image_session(image_name)
            if session == None:
                return  # issue already reported
            with session:
                run_modify_image_prompt(session)
                default_new_name = session.get_default_new_name()
                try:
                    while True:
                        print 'New image name [%s]:' % default_new_name,
                        new_name = raw_input()
                        if new_name == '':
                            new_name = default_new_name
                            break
                        else:
                            if session.validate_new_name(new_name):
                                break
                    session.select_new_name(new_name)
                except KeyboardInterrupt:
                    print 'Aborted.'

@WalTImage.subcommand("remove")
class WalTImageRemove(cli.Application):
    """remove an image"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            server.remove_image(image_name)

@WalTImage.subcommand("rename")
class WalTImageRename(cli.Application):
    """rename an image"""
    def main(self, image_name, new_name):
        with ClientToServerLink() as server:
            server.rename_image(image_name, new_name)

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
        conn = LogsConnectionToServer(conf['server'])
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
        run_sql_prompt()

def run():
    WalT.run()

if __name__ == "__main__":
    run()

