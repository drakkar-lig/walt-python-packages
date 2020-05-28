import contextlib
import time, sys
from plumbum import cli
from walt.client.device import WalTDevice

from walt.common.tools import format_sentence_about_nodes
from walt.client.link import ClientToServerLink
from walt.client.tools import confirm
from walt.client.config import conf
from walt.client.interactive import run_node_cmd, \
                                    run_device_ping, \
                                    NODE_SHELL_MESSAGE
from walt.client.transfer import run_transfer_with_node
from walt.client.expose import TCPExposer
from walt.client.application import WalTCategoryApplication, WalTApplication
from walt.client.timeout import start_timeout, stop_timeout, TimeoutException, cli_timeout_switch

WAIT_NODES_BUSY_LABEL='\
Node bootup notification still pending (press ctrl-C to proceed anyway)'

class WalTNode(WalTCategoryApplication):
    """WalT node management sub-commands"""
    @staticmethod
    def wait_for_nodes(server, node_set, busy_label = WAIT_NODES_BUSY_LABEL, timeout = -1):
        try:
            server.set_busy_label(busy_label)
            if timeout > 0:
                start_timeout(timeout)
            server.wait_for_nodes(node_set)
            if timeout > 0:
                stop_timeout()
            server.set_default_busy_label()
        except KeyboardInterrupt:
            print()
            server.set_default_busy_label()
        except TimeoutException:
            server.set_default_busy_label()
            print('Timeout was reached.')

    @staticmethod
    def run_cmd(node_set, several_nodes_allowed, cmdargs,
                startup_msg = None, tty = False):
        nodes_ip = None
        with ClientToServerLink() as server:
            if not WalTDevice.confirm_devices_not_owned(server, node_set):
                return
            nodes_ip = server.get_nodes_ip(node_set)
            if len(nodes_ip) == 0:
                return  # issue already reported
            elif len(nodes_ip) > 1 and not several_nodes_allowed:
                sys.stderr.write(
                    'Error: this command must target 1 node only.\n')
                return
            WalTNode.wait_for_nodes(server, node_set)
            server.prepare_ssh_access(node_set)
        if nodes_ip:
            for ip in nodes_ip:
                if startup_msg:
                    print(startup_msg)
                run_node_cmd(ip, cmdargs, tty)

    @staticmethod
    def boot_nodes(node_set, image_name_or_default):
        with ClientToServerLink() as server:
            if server.has_image(image_name_or_default, True):
                # the list of nodes the keyword "my-nodes" refers to
                # may be altered by the server.set_image() call, thus
                # we have to get a real list of nodes before starting
                # anything.
                node_set = server.develop_node_set(node_set)
                if node_set is None:
                    return
                if not WalTDevice.confirm_devices_not_owned(server, node_set):
                    return
                if not server.set_image(node_set, image_name_or_default):
                    return
                server.reboot_nodes(node_set)

@WalTNode.subcommand("show")
class WalTNodeShow(WalTApplication):
    """show WalT nodes"""
    _all = False # default
    def main(self):
        with ClientToServerLink() as server:
            print(server.show_nodes(conf['username'], self._all))
    @cli.autoswitch(help='show nodes used by other users too')
    def all(self):
        self._all = True

@WalTNode.subcommand("create")
class WalTNodeCreate(WalTApplication):
    """create a virtual WalT node"""
    def main(self, node_name):
        with ClientToServerLink() as server:
            server.create_vnode(node_name)

@WalTNode.subcommand("remove")
class WalTNodeRemove(WalTApplication):
    """remove a virtual WalT node"""
    def main(self, node_name):
        with ClientToServerLink() as server:
            if not WalTDevice.confirm_devices_not_owned(server, node_name):
                return
            server.remove_vnode(node_name)

@WalTNode.subcommand("rename")
class WalTNodeRename(WalTApplication):
    """rename a WalT node"""
    def main(self, old_node_name, new_node_name):
        with ClientToServerLink() as server:
            if not WalTDevice.confirm_devices_not_owned(server, old_node_name):
                 return
            server.rename(old_node_name, new_node_name)

@WalTNode.subcommand("blink")
class WalTNodeBlink(WalTApplication):
    """make a node blink for a given number of seconds"""
    def main(self, node_name, duration=60):
        try:
            seconds = int(duration)
        except:
            sys.stderr.write(
                '<duration> must be an integer (number of seconds).\n')
        else:
            with ClientToServerLink() as server:
                WalTNode.wait_for_nodes(server, node_name)
                if server.blink(node_name, True):
                    print('blinking for %ds... ' % seconds)
                    try:
                        time.sleep(seconds)
                        print('done.')
                    except KeyboardInterrupt:
                        print('Aborted.')
                    finally:
                        server.blink(node_name, False)

@WalTNode.subcommand("reboot")
class WalTNodeReboot(WalTApplication):
    """reboot a (set of) node(s)"""
    _hard_only = False # default
    def main(self, node_set):
        with ClientToServerLink() as server:
            if not WalTDevice.confirm_devices_not_owned(server, node_set):
                return
            server.reboot_nodes(node_set, self._hard_only)
    @cli.autoswitch(help='allow PoE-reboots only (power-cycle)')
    def hard(self):
        self._hard_only = True

@WalTNode.subcommand("boot")
class WalTNodeBoot(WalTApplication):
    """let a (set of) node(s) boot an operating system image"""
    def main(self, node_set, image_name_or_default):
        return WalTNode.boot_nodes(node_set, image_name_or_default)

@WalTNode.subcommand("deploy")
class WalTNodeDeploy(WalTApplication):
    """alias to 'boot' subcommand"""
    def main(self, node_set, image_name_or_default):
        return WalTNode.boot_nodes(node_set, image_name_or_default)

@WalTNode.subcommand("ping")
class WalTNodePing(WalTApplication):
    """check that a node is reachable on WalT network"""
    def main(self, node_name):
        node_ip = None
        with ClientToServerLink() as server:
            node_ip = server.get_node_ip(node_name)
        if node_ip:
            run_device_ping(node_ip)

@WalTNode.subcommand("shell")
class WalTNodeShell(WalTApplication):
    """run an interactive shell connected to the node"""
    def main(self, node_name):
        WalTNode.run_cmd(   node_name, False, [ ],
                            startup_msg = NODE_SHELL_MESSAGE,
                            tty = True)

@WalTNode.subcommand("run")
class WalTNodeRun(WalTApplication):
    """run a command on a (set of) node(s)"""
    _term = False # default
    def main(self, node_set, *cmdargs):
        WalTNode.run_cmd(node_set, True, cmdargs, tty = self._term)
    @cli.autoswitch(help='run command in a pseudo-terminal')
    def term(self):
        self._term = True

@WalTNode.subcommand("cp")
class WalTNodeCp(WalTApplication):
    """transfer files/dirs (client machine <-> node)"""
    def main(self, src, dst):
        with ClientToServerLink() as server:
            info = server.validate_node_cp(src, dst)
            if info == None:
                return
            if not info['node_owned'] and not confirm():
                return
            node_name = info['node_name']
            WalTNode.wait_for_nodes(server, node_name)
            try:
                run_transfer_with_node(**info)
            except (KeyboardInterrupt, EOFError):
                print()
                print('Aborted.')

@WalTNode.subcommand("wait")
class WalTNodeWait(WalTApplication):
    """wait for bootup notification of a node (or set of nodes)"""
    timeout = cli_timeout_switch()
    def main(self, node_set):
        with ClientToServerLink() as server_link:
            busy_label = 'Node bootup notification pending'
            WalTNode.wait_for_nodes(server_link, node_set, busy_label, self.timeout)

@WalTNode.subcommand("expose")
class WalTNodeExpose(WalTApplication):
    """expose a network port of a node on the local machine"""
    @cli.positional(str, int, int)
    def main(self, node_name, node_port, local_port):
        node_ip = None
        with ClientToServerLink() as server_link:
            node_ip = server_link.get_node_ip(node_name)
            if not node_ip:
                return
            WalTNode.wait_for_nodes(server_link, node_name)
            print('Listening on TCP port %d and redirecting connections to %s:%d.' % \
                            (local_port, node_name, node_port))
            exposer = TCPExposer(local_port, node_ip, node_port)
            exposer.run()

@WalTNode.subcommand("config")
class WalTNodeConfig(WalTApplication):
    """Get or set nodes configuration"""
    def main(self, node_set, *configuration):
        with ClientToServerLink() as server:
            node_set = server.develop_node_set(node_set)
            if node_set is None:
                return
            if len(configuration) > 0:
                if not WalTDevice.confirm_devices_not_owned(server, node_set):
                    return
                server.set_device_config(node_set, configuration)
            else:
                # no settings specified => list current settings
                server.get_device_config(node_set)
