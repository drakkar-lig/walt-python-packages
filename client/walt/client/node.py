import sys
import time

from plumbum import cli
from walt.client.application import WalTApplication, WalTCategoryApplication
from walt.client.config import conf
from walt.client.link import ClientToServerLink
from walt.client.timeout import TimeoutException, cli_timeout_switch, timeout_context
from walt.client.tools import confirm
from walt.client.types import (
    IMAGE_OR_DEFAULT,
    NODE,
    NODE_CONFIG_PARAM,
    NODE_CP_DST,
    NODE_CP_SRC,
    SET_OF_NODES,
)
from walt.common.tools import SilentBusyIndicator

WAIT_NODES_BUSY_LABEL = (
    "Node bootup notification still pending (press ctrl-C to proceed anyway)"
)


class WalTNode(WalTCategoryApplication):
    """management of WalT nodes"""

    ORDERING = 2

    @staticmethod
    def wait_for_nodes(server, node_set, busy_label=WAIT_NODES_BUSY_LABEL, timeout=-1):
        try:
            server.set_busy_label(busy_label)
            with timeout_context(timeout):
                server.wait_for_nodes(node_set)
            server.set_default_busy_label()
            return True
        except KeyboardInterrupt:
            print()
            server.set_default_busy_label()
            return False
        except TimeoutException:
            server.set_default_busy_label()
            print("Timeout was reached.")
            return False

    @staticmethod
    def run_cmd(
        node_set,
        several_nodes_allowed,
        cmdargs,
        startup_msg=None,
        tty=False,
        capture_output=False,
    ):
        nodes_ip = None
        if several_nodes_allowed and capture_output:
            sys.stderr.write("Error: Only one node allowed when capturing output.\n")
            return
        with ClientToServerLink() as server:
            if not WalTNode.check_nodes_ownership(server, node_set):
                return
            nodes_ip = server.get_nodes_ip(node_set)
            if len(nodes_ip) == 0:
                return  # issue already reported
            elif len(nodes_ip) > 1 and not several_nodes_allowed:
                sys.stderr.write("Error: this command must target 1 node only.\n")
                return
            if not WalTNode.wait_for_nodes(server, node_set):
                return False
        if nodes_ip:
            for ip in nodes_ip:
                if startup_msg:
                    print(startup_msg)
                from walt.client.interactive import run_node_cmd
                res = run_node_cmd(ip, cmdargs, tty, capture_output)
                if capture_output:
                    return res

    @staticmethod
    def run_console(node_name):
        indicator = SilentBusyIndicator()
        with ClientToServerLink(busy_indicator=indicator) as server:
            if not WalTNode.check_nodes_ownership(server, node_name):
                return
            nodes_info = server.get_nodes_info(node_name)
            if len(nodes_info) == 0:
                return  # issue already reported
            elif len(nodes_info) > 1:
                sys.stderr.write("Error: this command must target 1 node only.\n")
                return
            node_info = nodes_info[0]
            if node_info["virtual"] is False:
                sys.stderr.write("Error: console is only available on virtual nodes.\n")
                return
            from walt.client.console import run_node_console
            run_node_console(server, node_info)

    @staticmethod
    def boot_nodes(node_set, image_name_or_default, cause,
                   ownership_mode="owned-or-free"):
        with ClientToServerLink() as server:
            if server.has_image(image_name_or_default, True):
                # the list of nodes keywords "my-nodes" or "free-nodes" refers to
                # may be altered by the server.set_image() call, thus
                # we have to get a real list of nodes before starting
                # anything.
                node_set = server.develop_node_set(node_set)
                if node_set is None:
                    return
                if not WalTNode.check_nodes_ownership(server, node_set, ownership_mode):
                    return
                if not server.set_image(node_set, image_name_or_default):
                    return
                server.set_busy_label("Rebooting")
                server.reboot_nodes(node_set, cause=cause)

    @staticmethod
    def check_nodes_ownership(
        server, node_set, mode="owned-or-free", ignore_other_devices=False
    ):
        from walt.common.formatting import format_sentence

        owned, free, not_owned, not_nodes = server.filter_ownership(node_set)
        if len(owned) + len(free) + len(not_owned) + len(not_nodes) == 0:
            return False  # error during api call, already reported
        if not ignore_other_devices and len(not_nodes) > 0:
            sys.stderr.write(
                format_sentence(
                    "Error: %s is(are) not a() WalT node(nodes).",
                    not_nodes,
                    "",
                    "Device",
                    "Devices",
                ).replace('  ', ' ')
                + " Aborting.\n"
            )
            return False
        if mode == "free-or-not-owned" and len(owned) > 0:
            sys.stderr.write(
                format_sentence(
                    (
                        "Error: %s is(are) already yours."
                        " See `walt help show node-ownership`."
                    ),
                    owned,
                    "",
                    "Node",
                    "Nodes",
                )
                + "\n"
            )
            return False
        if mode == "owned" and len(free) + len(not_owned) > 0:
            sys.stderr.write(
                format_sentence(
                    "Error: %s is(are) not yours. See `walt help show node-ownership`.",
                    free + not_owned,
                    "",
                    "Node",
                    "Nodes",
                )
                + "\n"
            )
            return False
        if mode in ("owned-or-free", "free-or-not-owned") and len(not_owned) > 0:
            sys.stderr.write(
                format_sentence(
                    "Warning: %s seems(seem) to be used by another(other) user(users).",
                    not_owned,
                    "",
                    "Node",
                    "Nodes",
                )
                + "\n"
            )
            if not confirm():
                return False
        return True


@WalTNode.subcommand("show")
class WalTNodeShow(WalTApplication):
    """show WalT nodes"""

    ORDERING = 1
    _all = False  # default
    _names_only = False  # default

    def main(self):
        with ClientToServerLink() as server:
            print(server.show_nodes(conf.walt.username, self._all, self._names_only))

    @cli.autoswitch(help="show nodes used by other users too")
    def all(self):
        self._all = True

    @cli.autoswitch(help="list node names only")
    def names_only(self):
        self._names_only = True


@WalTNode.subcommand("create")
class WalTNodeCreate(WalTApplication):
    """create a virtual WalT node"""

    ORDERING = 10

    def main(self, node_name: NODE):
        with ClientToServerLink() as server:
            server.create_vnode(node_name)


@WalTNode.subcommand("remove")
class WalTNodeRemove(WalTApplication):
    """remove a virtual WalT node"""

    ORDERING = 11

    def main(self, node_name: NODE):
        with ClientToServerLink() as server:
            if not WalTNode.check_nodes_ownership(server, node_name):
                return
            server.remove_vnode(node_name)


@WalTNode.subcommand("rename")
class WalTNodeRename(WalTApplication):
    """rename a WalT node"""

    ORDERING = 12

    def main(self, old_node_name: NODE, new_node_name):
        with ClientToServerLink() as server:
            if not WalTNode.check_nodes_ownership(server, old_node_name):
                return
            server.rename(old_node_name, new_node_name)


@WalTNode.subcommand("blink")
class WalTNodeBlink(WalTApplication):
    """make a node blink for a given number of seconds"""

    ORDERING = 15

    def main(self, node_name: NODE, duration=60):
        try:
            seconds = int(duration)
        except Exception:
            sys.stderr.write("<duration> must be an integer (number of seconds).\n")
        else:
            with ClientToServerLink() as server:
                if not WalTNode.wait_for_nodes(server, node_name):
                    return False
                if server.blink(node_name, True):
                    print("blinking for %ds... " % seconds)
                    try:
                        time.sleep(seconds)
                        print("done.")
                    except KeyboardInterrupt:
                        print("Aborted.")
                        return False
                    finally:
                        server.blink(node_name, False)


@WalTNode.subcommand("reboot")
class WalTNodeReboot(WalTApplication):
    """reboot a (set of) node(s)"""

    ORDERING = 8
    _hard_only = False  # default

    def main(self, node_set: SET_OF_NODES):
        with ClientToServerLink() as server:
            if not WalTNode.check_nodes_ownership(server, node_set):
                return
            server.reboot_nodes(node_set, hard_only=self._hard_only)

    @cli.autoswitch(help="allow PoE-reboots only (power-cycle)")
    def hard(self):
        self._hard_only = True


@WalTNode.subcommand("acquire")
class WalTNodeAcquire(WalTApplication):
    """get ownership of a (set of) node(s)"""

    ORDERING = 2

    def main(self, node_set: SET_OF_NODES):
        with ClientToServerLink() as server:
            if not WalTNode.check_nodes_ownership(
                server, node_set, "free-or-not-owned"
            ):
                return False
            # get info about images clones, possibly clone them
            valid, _, image_per_node = server.get_clones_of_default_images(node_set)
            if not valid:
                return False  # already reported
            # the list of nodes keywords "my-nodes" or "free-nodes" refers to
            # may be altered by the server.set_image() call, thus
            # we have to get a real list of nodes before starting
            # anything.
            node_set = server.develop_node_set(node_set)
            # revert image_per_node dictionary
            from collections import defaultdict

            nodes_per_image = defaultdict(list)
            for node, image in image_per_node.items():
                nodes_per_image[image].append(node)
            # associate nodes with appropriate image
            for image, nodes in nodes_per_image.items():
                image_node_set = ",".join(nodes)
                if not server.set_image(image_node_set, image):
                    return False  # unexpected issue
            # reboot
            server.set_busy_label("Rebooting")
            server.reboot_nodes(node_set, cause="acquire")


@WalTNode.subcommand("release")
class WalTNodeRelease(WalTApplication):
    """release ownership of a (set of) node(s)"""

    ORDERING = 3

    def main(self, node_set: SET_OF_NODES):
        return WalTNode.boot_nodes(node_set, "default", "release", "owned")


@WalTNode.subcommand("boot")
class WalTNodeBoot(WalTApplication):
    """let a (set of) node(s) boot an operating system image"""

    ORDERING = 4

    def main(self, node_set: SET_OF_NODES, image_name_or_default: IMAGE_OR_DEFAULT):
        return WalTNode.boot_nodes(node_set, image_name_or_default, "image change")


@WalTNode.subcommand("deploy")
class WalTNodeDeploy(WalTApplication):
    """alias to 'boot' subcommand"""

    ORDERING = 18

    def main(self, node_set: SET_OF_NODES, image_name_or_default: IMAGE_OR_DEFAULT):
        return WalTNode.boot_nodes(node_set, image_name_or_default, "image change")


@WalTNode.subcommand("ping")
class WalTNodePing(WalTApplication):
    """check that a node is reachable on WalT network"""

    ORDERING = 13

    def main(self, node_name: NODE):
        node_ip = None
        with ClientToServerLink() as server:
            node_ip = server.get_node_ip(node_name)
        if node_ip:
            from walt.client.interactive import run_device_ping
            run_device_ping(node_ip)


@WalTNode.subcommand("console")
class WalTNodeConsole(WalTApplication):
    """connect to the console of a WalT node"""

    ORDERING = 14

    def main(self, node_name: NODE):
        WalTNode.run_console(node_name)


@WalTNode.subcommand("shell")
class WalTNodeShell(WalTApplication):
    """run an interactive shell connected to the node"""

    ORDERING = 5

    def main(self, node_name: NODE):
        from walt.client.interactive import NODE_SHELL_MESSAGE
        WalTNode.run_cmd(node_name, False, [], startup_msg=NODE_SHELL_MESSAGE, tty=True)


@WalTNode.subcommand("run")
class WalTNodeRun(WalTApplication):
    """run a command on a (set of) node(s)"""

    ORDERING = 6
    _term = False  # default

    def main(self, node_set: SET_OF_NODES, *cmdargs):
        WalTNode.run_cmd(node_set, True, cmdargs, tty=self._term)

    @cli.autoswitch(help="run command in a pseudo-terminal")
    def term(self):
        self._term = True


@WalTNode.subcommand("cp")
class WalTNodeCp(WalTApplication):
    """transfer files/dirs to or from a node"""

    ORDERING = 7
    USAGE = """\
    walt node cp <local-path> <node>:<path>
    walt node cp <node>:<path> <local-path>
    walt node cp <node>:<path> booted-image
    """

    def main(self, src: NODE_CP_SRC, dst: NODE_CP_DST):
        with ClientToServerLink() as server:
            info = server.validate_node_cp(src, dst)
            if info is None:
                return
            if info["status"] == "FAILED":
                return False
            if info["node_ownership"] == "not_owned":
                print(f"Warning: {info['node_name']} seems to be used by another user.")
                info["status"] = "NEEDS_CONFIRM"
            if info["status"] == "NEEDS_CONFIRM":
                if confirm():
                    info["status"] = "OK"
                else:
                    return False  # give up
            node_name = info["node_name"]
            if not WalTNode.wait_for_nodes(server, node_name):
                return False
            if dst == "booted-image":
                path_info = dict(
                    src_path=info["src_path"],
                    dst_dir=info["dst_dir"],
                    dst_name=info["dst_name"],
                )
                server.node_cp_to_booted_image(node_name, **path_info)
            else:
                from walt.client.transfer import run_transfer_with_node
                try:
                    run_transfer_with_node(**info)
                except (KeyboardInterrupt, EOFError):
                    print()
                    print("Aborted.")
                    return False


@WalTNode.subcommand("wait")
class WalTNodeWait(WalTApplication):
    """wait for bootup notification of a node (or set of nodes)"""

    ORDERING = 16
    timeout = cli_timeout_switch()

    def main(self, node_set: SET_OF_NODES):
        with ClientToServerLink() as server_link:
            busy_label = "Node bootup notification pending"
            return WalTNode.wait_for_nodes(
                server_link, node_set, busy_label, self.timeout
            )


@WalTNode.subcommand("expose")
class WalTNodeExpose(WalTApplication):
    """expose a network port of a node on the local machine"""

    ORDERING = 17

    @cli.positional(str, int, int)
    def main(self, node_name: NODE, node_port, local_port):
        node_ip = None
        with ClientToServerLink() as server_link:
            node_ip = server_link.get_node_ip(node_name)
            if not node_ip:
                return False
            if not WalTNode.wait_for_nodes(server_link, node_name):
                return False
            print(
                "Listening on TCP port %d and redirecting connections to %s:%d."
                % (local_port, node_name, node_port)
            )
            from walt.client.expose import TCPExposer
            exposer = TCPExposer(local_port, node_ip, node_port)
            exposer.run()


@WalTNode.subcommand("config")
class WalTNodeConfig(WalTApplication):
    """get or set nodes configuration"""

    ORDERING = 9

    def main(self, node_set: SET_OF_NODES, *configuration: NODE_CONFIG_PARAM):
        with ClientToServerLink() as server:
            node_set = server.develop_node_set(node_set)
            if node_set is None:
                return
            if len(configuration) > 0:
                if not WalTNode.check_nodes_ownership(server, node_set):
                    return
                server.set_device_config(node_set, configuration)
            else:
                # no settings specified => list current settings
                server.get_device_config(node_set)
