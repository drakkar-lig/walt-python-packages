#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import readline, time, sys, socket
from plumbum import cli
from walt.client import myhelp
from walt.client.link import ClientToServerLink, ResponseQueue
from walt.client.tools import confirm
from walt.client.logs import WaltLog
from walt.client.interactive import run_sql_prompt, \
                                    run_image_shell_prompt, \
                                    run_node_shell, \
                                    run_device_ping

WALT_VERSION = "0.1"
POE_REBOOT_DELAY            = 2  # seconds

myhelp.register_topic('shells', """
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
""")

myhelp.register_topic('node-terminology', """
* 'owning' a node
* ---------------
In WalT terminology, if node <N> is deployed with an image created by user <U>,
we consider that "<U> owns <N>".

Thus, if you just started using WalT, "you do not own any node" until you deploy
an image on one of them (use 'walt node deploy <node(s)> <image>' for this).

* specifying a set of nodes 
* -------------------------
Some commands accept a "set of nodes":
- walt node deploy
- walt node reboot
- walt log show         (see option '--nodes')

In this case you can specify either:
* the keyword 'my-nodes' (this will select the nodes that you own)
* the keyword 'all-nodes'
* a coma separated list of nodes (e.g "rpi1,rpi2" or just "rpi1")
""")

class WalT(cli.Application):
    """WalT (wireless testbed) control tool."""
    VERSION = WALT_VERSION

    @cli.switch(["-z", "--help-about"], str,
                group = "Meta-switches")
    def help_about(self, topic):
        """Prints help details about a given topic.
           Run 'walt --help-about help' to list them.
        """
        print myhelp.get(topic)
        sys.exit()

@WalT.subcommand("device")
class WalTDevice(cli.Application):
    """management of WalT platform devices"""

@WalTDevice.subcommand("tree")
class WalTDeviceTree(cli.Application):
    """print the network structure of the platform"""
    def main(self):
        with ClientToServerLink() as server:
            print server.device_tree()

@WalTDevice.subcommand("show")
class WalTDeviceShow(cli.Application):
    """print details about devices involved in the platform"""
    def main(self):
        with ClientToServerLink() as server:
            print server.device_show()

@WalTDevice.subcommand("rescan")
class WalTDeviceRescan(cli.Application):
    """rescan the network devices involved in the platform"""
    def main(self):
        with ClientToServerLink() as server:
            server.device_rescan()

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

MSG_REACHABLE_CANNOT_FORGET = """\
Failed: %s is reachable on the WalT network (thus supposedly in use).
You can use 'walt device rescan' to update this.
"""
@WalTDevice.subcommand("forget")
class WalTDeviceForget(cli.Application):
    """let the WalT system forget about an obsolete device"""
    _force = False # default
    def main(self, device_name):
        with ClientToServerLink() as server:
            reachable = server.is_device_reachable(device_name)
            if reachable == None:
                return  # issue already reported
            if reachable:
                print MSG_REACHABLE_CANNOT_FORGET % device_name
                return
            if not self._force:
                logs_cnt = server.count_logs(senders = set([device_name]))
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
class WalTNodeShow(cli.Application):
    """show WalT nodes"""
    _all = False # default
    def main(self):
        with ClientToServerLink() as server:
            print server.show_nodes(self._all)
    @cli.autoswitch(help='show nodes used by other users too')
    def all(self):
        self._all = True

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
    """reboot a (set of) node(s)"""
    def main(self, node_set):
        with ClientToServerLink() as server:
            not_owned = server.includes_nodes_not_owned(node_set, warn=True)
            if not_owned == None:
                return
            if not_owned == True:
                if not confirm():
                    return
            if server.poweroff(node_set, warn_unreachable=True):
                time.sleep(POE_REBOOT_DELAY)
                server.poweron(node_set, warn_unreachable=False)

@WalTNode.subcommand("deploy")
class WalTNodeDeploy(cli.Application):
    """deploy an operating system image on a (set of) node(s)"""
    def main(self, node_set, image_name):
        with ClientToServerLink() as server:
            if server.has_image(image_name):
                not_owned = server.includes_nodes_not_owned(node_set, warn=True)
                if not_owned == None:
                    return
                if not_owned == True:
                    if not confirm():
                        return
                if server.poweroff(node_set, warn_unreachable=True):
                    server.set_image(node_set, image_name, warn_unreachable=False)
                    time.sleep(POE_REBOOT_DELAY)
                    server.poweron(node_set, warn_unreachable=False)

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

@WalTImage.subcommand("search")
class WalTImageSearch(cli.Application):
    """search for remote WalT node OS images"""
    def main(self, keyword=None):
        with ClientToServerLink(True) as server:
            q = ResponseQueue()
            server.search_images(q, keyword)
            print q.get()

@WalTImage.subcommand("clone")
class WalTImageClone(cli.Application):
    """clone a remote image into your working set"""
    _force = False # default
    def main(self, clonable_image_link):
        q = ResponseQueue()
        with ClientToServerLink(True) as server:
            server.clone_image(q, clonable_image_link, self._force)
            q.wait()
    @cli.autoswitch(help='do it, even if it overwrites an existing image.')
    def force(self):
        self._force = True

@WalTImage.subcommand("show")
class WalTImageShow(cli.Application):
    """display your working set of walt images"""
    def main(self):
        with ClientToServerLink() as server:
            print server.show_images()

@WalTImage.subcommand("shell")
class WalTImageShell(cli.Application):
    """modify an image through an interactive shell"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            session = server.create_image_shell_session(
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
                            print 'Selected: %s' % new_name
                        res = session.validate_new_name(new_name)
                        if res == session.NAME_NEEDS_CONFIRM:
                            if confirm():
                                res = session.NAME_OK
                            else:
                                res = session.NAME_NOT_OK
                        if res == session.NAME_OK:
                            break
                        if res == session.NAME_NOT_OK:
                            continue
                    # we left the loop, this means we have a valid name
                    session.select_new_name(new_name)
                except (KeyboardInterrupt, EOFError):
                    print 'Aborted.'

@WalTImage.subcommand("remove")
class WalTImageRemove(cli.Application):
    """remove an image from your working set"""
    def main(self, image_name):
        with ClientToServerLink() as server:
            server.remove_image(image_name)

@WalTImage.subcommand("rename")
class WalTImageRename(cli.Application):
    """rename an image of your working set"""
    def main(self, image_name, new_image_name):
        with ClientToServerLink() as server:
            server.rename_image(image_name, new_image_name)

@WalTImage.subcommand("copy")
class WalTImageCopy(cli.Application):
    """copy an image of your working set"""
    def main(self, image_name, new_image_name):
        with ClientToServerLink() as server:
            server.copy_image(image_name, new_image_name)

WalT.subcommand("log", WaltLog)

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
    """fix the owner of images"""
    _force = False # default
    def main(self, other_user):
        if not self._force:
            print """\
This will make you own all images of user '%s'. It is intended
for maintenance only (i.e. if user '%s' is no longer working with
walt).
If this is really what you want, run:
walt advanced fix-image-owner --yes-i-know-do-it-please %s
""" % ((other_user,) * 3)
        else:
            with ClientToServerLink() as server:
                server.fix_image_owner(other_user)
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

