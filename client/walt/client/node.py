import time, sys
from plumbum import cli
from walt.client import myhelp
from walt.client.link import ClientToServerLink
from walt.client.tools import confirm
from walt.client.interactive import run_node_shell, \
                                    run_device_ping
from walt.client.transfer import run_transfer_with_node

POE_REBOOT_DELAY            = 2  # seconds

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

class WalTNode(cli.Application):
    """WalT node management sub-commands"""
    pass

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

@WalTNode.subcommand("cp")
class WalTNodeCp(cli.Application):
    """transfer files/dirs (client machine <-> node)"""
    def main(self, src, dst):
        with ClientToServerLink() as server:
            info = server.validate_node_cp(src, dst)
            if info == None:
                return
            info = { k:v for k,v in info }
            try:
                run_transfer_with_node(**info)
            except (KeyboardInterrupt, EOFError):
                print
                print 'Aborted.'

