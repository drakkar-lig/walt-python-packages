#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import readline, time, sys, socket
from plumbum import cli
from walt.common.logs import LogsConnectionToServer
from walt.client.link import ClientToServerLink
from walt.client.config import conf, conf_path
from walt.client.interactive import run_sql_prompt, \
                                    run_image_shell_prompt, \
                                    run_node_shell, \
                                    run_device_ping

WALT_VERSION = "0.1"
DEFAULT_FORMAT_STRING= \
   '{timestamp:%H:%M:%S.%f} {sender}.{stream} -> {line}'
POE_REBOOT_DELAY            = 2  # seconds
HELP_SHELL = """
                | walt node shell    | walt image shell
------------------------------------------------------------
persistence     | until the node     | yes
                | reboots (1)        |
------------------------------------------------------------
backend         | the real node      | virtual environment
                |                    | ARM CPU emulation (2)
------------------------------------------------------------
target workflow | testing/debugging  | apply changes
                |                    |
------------------------------------------------------------

(1): Changes are lost on reboot. This ensures that a node booting a
given image will always act the same. 

(2): Avoid heavy processing, such as compiling of a large
source code base. In this case, cross-compiling on another machine
and importing the build artefacts in the virtual environment (through
the emulated network) should be the prefered option.
Also, keep in mind that in the virtual environment (docker container)
no services are running (no init process, etc). Actually, the only
process running in this virtual environment when you enter it is the
shell process itself.
"""

class WalT(cli.Application):
    """WalT (wireless testbed) control tool."""
    VERSION = WALT_VERSION
    help_messages = []

    @cli.switch(["-z", "--help-shell"], \
                group = "Meta-switches")
    def help_shell(self):
        """Help about usage of 'node shell' and 'image shell'."""
        self.help_messages.append(HELP_SHELL)

    def main(self, *args):
        if len(self.help_messages) > 0:
            for msg in self.help_messages:
                print msg
            sys.exit()
        # display the help if no subcommand specified
        if not self.nested_command:
            sys.argv.append('--help')
            self.__class__.run()

@WalT.subcommand("device")
class WalTDevice(cli.Application):
    """management of WalT platform devices"""

@WalTDevice.subcommand("show")
class WalTDevicePrint(cli.Application):
    """print a view of the devices involved in the platform"""
    _details = False # default
    def main(self):
        with ClientToServerLink() as server:
            print server.describe(self._details)
    @cli.autoswitch(help='Print more detailed information.')
    def details(self):
        self._details = True

@WalTDevice.subcommand("rescan")
class WalTDeviceRescan(cli.Application):
    """rescan the network devices involved in the platform"""
    def main(self):
        with ClientToServerLink() as server:
            server.update()

@WalTDevice.subcommand("rename")
class WalTRenameDevice(cli.Application):
    """rename a device"""
    def main(self, old_name, new_name):
        with ClientToServerLink() as server:
            server.rename(old_name, new_name)

@WalTDevice.subcommand("ping")
class WalTDevicePing(cli.Application):
    """check that a device is reachable on WalT network"""
    def main(self, device_name):
        device_ip = None
        with ClientToServerLink() as server:
            device_ip = server.get_device_ip(device_name)
        if device_ip:
            run_device_ping(device_ip)

MSG_FORGET_DEVICE_WITH_LOGS = """\
This would delete any information about %s, including %s log \
lines.
If this is what you want, run 'walt node forget --force %s'."""

@WalTDevice.subcommand("forget")
class WalTDeviceForget(cli.Application):
    """let the WalT system forget about an obsolete device"""
    _force = False # default
    def main(self, device_name):
        with ClientToServerLink() as server:
            if server.check_device_exists(device_name):
                if not server.is_disconnected(device_name):
                    print '%s seems currently connected to the WalT network. Cannot forget it!' \
                             % device_name
                    return
                if not self._force:
                    logs_cnt = server.count_logs(device_name)
                    if logs_cnt > 0:
                        print MSG_FORGET_DEVICE_WITH_LOGS % (
                            device_name, logs_cnt, device_name
                        )
                        return  # give up for now
                # ok, do it
                server.forget(device_name)
                print 'done.'
    @cli.autoswitch(help='do it, even if related data will be lost')
    def force(self):
        self._force = True

@WalT.subcommand("node")
class WalTNode(cli.Application):
    """WalT node management sub-commands"""

@WalTNode.subcommand("show")
class WalTNodeList(cli.Application):
    """list available WalT nodes"""
    def main(self):
        with ClientToServerLink() as server:
            print server.list_nodes()

@WalTNode.subcommand("blink")
class WalTNodeBlink(cli.Application):
    """make a node blink for a given number of seconds"""
    def main(self, node_name, duration=60):
        try:
            seconds = int(duration)
        except:
            sys.stderr.write(
                '<duration> must be an integer (number of seconds).\n')
        else:
            with ClientToServerLink() as server:
                if server.blink(node_name, True):
                    print 'blinking for %ds... ' % seconds
                    try:
                        time.sleep(seconds)
                        print 'done.'
                    except KeyboardInterrupt:
                        print 'Aborted.'
                    finally:
                        server.blink(node_name, False)

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

@WalTNode.subcommand("ping")
class WalTNodePing(cli.Application):
    """check that a node is reachable on WalT network"""
    def main(self, node_name):
        node_ip = None
        with ClientToServerLink() as server:
            node_ip = server.get_node_ip(node_name)
        if node_ip:
            run_device_ping(node_ip)

@WalTNode.subcommand("shell")
class WalTNodeShell(cli.Application):
    """run an interactive shell connected to the node"""
    def main(self, node_name):
        node_ip = None
        with ClientToServerLink() as server:
            node_ip = server.get_reachable_node_ip(node_name)
        if node_ip:
            run_node_shell(node_ip)

@WalT.subcommand("image")
class WalTImage(cli.Application):
    """management of WalT-nodes operating system images"""

@WalTImage.subcommand("show")
class WalTImageShow(cli.Application):
    """list available WalT node OS images"""
    def main(self):
        with ClientToServerLink() as server:
            users = set(conf['friends'])
            users.add(conf['username'])
            print server.list_images(users)
            print '\nSelected users: %s.\n(conforming to %s)' % \
                    (', '.join(users), conf_path)

@WalTImage.subcommand("set-default")
class WalTImageSetDefault(cli.Application):
    """set the default image to be booted when a node connects
       to the server for the first time"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            server.set_default_image(image_name)

@WalTImage.subcommand("shell")
class WalTImageShell(cli.Application):
    """run an interactive shell allowing to modify a given
       image"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            session = server.create_modify_image_session(
                            image_name)
            if session == None:
                return  # issue already reported
            with session:
                run_image_shell_prompt(session)
                default_new_name = session.get_default_new_name()
                try:
                    while True:
                        new_name = raw_input(\
                            'New image name [%s]: ' % default_new_name)
                        if new_name == '':
                            new_name = default_new_name
                            break
                        else:
                            if session.validate_new_name(new_name):
                                break
                    session.select_new_name(new_name)
                except (KeyboardInterrupt, EOFError):
                    print 'Aborted.'

MSG_NOT_OWNER_OF_IMAGE = """\
You do not own this image. Owner is %s.
If this is really what you want, run this before:
walt advanced fix-image-owner %s"""

def verify_owner(server, image_name):
    owner = server.get_image_owner(image_name)
    if owner == None:
        return False # issue already reported
    if owner != conf['username']:
        print MSG_NOT_OWNER_OF_IMAGE % (owner, image_name)
        return False # give up
    return True

@WalTImage.subcommand("remove")
class WalTImageRemove(cli.Application):
    """remove an image"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            if verify_owner(server, image_name):
                server.remove_image(image_name)

@WalTImage.subcommand("rename")
class WalTImageRename(cli.Application):
    """rename an image"""
    def main(self, image_name, new_name):
        with ClientToServerLink() as server:
            if verify_owner(server, image_name):
                server.rename_image(image_name, new_name)

@WalT.subcommand("log")
class WaltLog(cli.Application):
    """management of logs"""

@WaltLog.subcommand("show")
class WaltLogShow(cli.Application):
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
                sys.stdout.flush()
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

@WalTAdvanced.subcommand("fix-image-owner")
class WalTAdvancedFixImageOwner(cli.Application):
    """fix the owner of an image"""
    _force = False # default
    def main(self, image_name):
        if not self._force:
            print """\
This will change the owner of an image to you. It is intended
for maintenance only (e.g. when a user is no longer working with
walt and you want to work with the images he created).
If this is really what you want, run:
walt advanced fix-image-owner --yes-i-know-do-it-please %s
""" % image_name
        else:
            with ClientToServerLink() as server:
                server.fix_image_owner(image_name)
    @cli.autoswitch(help='yes, I know, do it!')
    def yes_i_know_do_it_please(self):
        self._force = True

def run():
    try:
        WalT.run()
    except socket.error:
        print 'Network connection to WalT server failed.'

if __name__ == "__main__":
    run()

