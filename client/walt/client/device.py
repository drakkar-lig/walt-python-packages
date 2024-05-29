from plumbum import cli
from walt.client.application import WalTApplication, WalTCategoryApplication
from walt.client.expose import TCPExposer
from walt.client.interactive import run_device_ping, run_device_shell
from walt.client.link import ClientToServerLink
from walt.client.types import (
    DEVICE,
    DEVICE_CONFIG_PARAM,
    RESCAN_SET_OF_DEVICES,
    SET_OF_DEVICES,
    SWITCH,
    PORT_CONFIG_PARAM,
)


class WalTDevice(WalTCategoryApplication):
    """management of WalT platform devices"""

    ORDERING = 4

    @staticmethod
    def confirm_devices_not_owned(server, device_set):
        from walt.client.node import WalTNode

        # if some of the devices are nodes owned by someone else,
        # ask confirmation before proceeding
        return WalTNode.check_nodes_ownership(
            server, device_set, ignore_other_devices=True
        )


@WalTDevice.subcommand("tree")
class WalTDeviceTree(WalTApplication):
    """print the network structure of the platform"""

    ORDERING = 3
    _all = False  # default

    def main(self):
        with ClientToServerLink() as server:
            print(server.device_tree(self._all))

    @cli.autoswitch(help="show all devices detected")
    def all(self):
        self._all = True


@WalTDevice.subcommand("show")
class WalTDeviceShow(WalTApplication):
    """print details about devices involved in the platform"""

    ORDERING = 1

    def main(self):
        with ClientToServerLink() as server:
            print(server.device_show())


MSG_USE_WALT_NODE_SHELL = """\
%(node)s is a node. Use 'walt node shell %(node)s' instead."""


@WalTDevice.subcommand("shell")
class WalTDeviceShell(WalTApplication):
    """run an interactive ssh session to a device"""

    ORDERING = 2
    user = cli.SwitchAttr(
        "--user", str, argname="USER", help="""SSH user name"""
    )

    def main(self, device_name: DEVICE):
        with ClientToServerLink() as server:
            # check if device is a node
            device_info = server.get_device_info(device_name)
            if device_info is None:
                return False  # issue already reported
            if device_info["type"] == "node":
                print(MSG_USE_WALT_NODE_SHELL % dict(node=device_name))
                return False
            if self.user is None:
                self.user = input("SSH user name: ")
            if len(self.user) == 0:
                self.user = "root"
            run_device_shell(device_info["ip"], self.user)


@WalTDevice.subcommand("expose")
class WalTDeviceExpose(WalTApplication):
    """expose a network port of a device on the local machine"""

    ORDERING = 9

    @cli.positional(str, int, int)
    def main(self, device_name: DEVICE, device_port, local_port):
        device_ip = None
        with ClientToServerLink() as server:
            device_info = server.get_device_info(device_name)
            if device_info is None:
                return False  # issue already reported
            if not WalTDevice.confirm_devices_not_owned(server, device_name):
                return False
            device_ip = device_info["ip"]
            print(
                "Listening on TCP port %d and redirecting connections to %s:%d."
                % (local_port, device_name, device_port)
            )
            exposer = TCPExposer(local_port, device_ip, device_port)
            exposer.run()


@WalTDevice.subcommand("rescan")
class WalTDeviceRescan(WalTApplication):
    """rescan the network devices involved in the platform"""

    ORDERING = 4

    def main(self, device_set: RESCAN_SET_OF_DEVICES = "server,explorable-switches"):
        with ClientToServerLink() as server:
            server.device_rescan(device_set)


@WalTDevice.subcommand("rename")
class WalTRenameDevice(WalTApplication):
    """rename a device"""

    ORDERING = 5

    def main(self, old_name: DEVICE, new_name):
        with ClientToServerLink() as server:
            server.rename(old_name, new_name)


@WalTDevice.subcommand("port-config")
class WalTDevicePortConfig(WalTApplication):
    """view and edit switch port config and names"""

    ORDERING = 10

    def main(self, switch_name: SWITCH, port_id: int = None,
             *configuration: PORT_CONFIG_PARAM):
        with ClientToServerLink() as server:
            if len(configuration) > 0:
                server.set_port_config(switch_name, port_id, configuration)
            else:
                # no settings specified => list current settings
                server.get_port_config(switch_name, port_id)


@WalTDevice.subcommand("ping")
class WalTDevicePing(WalTApplication):
    """check that a device is reachable on WalT network"""

    ORDERING = 7

    def main(self, device_name: DEVICE):
        device_ip = None
        with ClientToServerLink() as server:
            device_ip = server.get_device_ip(device_name)
        if device_ip:
            run_device_ping(device_ip)


MSG_FORGET_DEVICE_WITH_LOGS = """\
This would delete any information about %s, including %s log \
lines.
If this is what you want, run 'walt device forget --force %s'."""

MSG_USE_WALT_NODE_REMOVE = """\
%(node)s is a virtual node. Use 'walt node remove %(node)s' instead."""


@WalTDevice.subcommand("forget")
class WalTDeviceForget(WalTApplication):
    """let the WalT system forget about an obsolete device"""

    ORDERING = 8
    _force = False  # default

    def main(self, device_name: DEVICE):
        with ClientToServerLink() as server:
            # check if server knows this device
            device_info = server.get_device_info(device_name)
            if device_info is None:
                return  # issue already reported
            if device_info["type"] == "node" and device_info["virtual"]:
                print(MSG_USE_WALT_NODE_REMOVE % dict(node=device_name))
                return
            if not self._force:
                # note: do not count logs of "*console" streams
                logs_cnt = server.count_logs(
                    history=(None, None),
                    issuers=set([device_name]),
                    streams="$(?<!console)",
                )
                if logs_cnt > 0:
                    print(
                        MSG_FORGET_DEVICE_WITH_LOGS
                        % (device_name, logs_cnt, device_name)
                    )
                    return  # give up for now
            # ok, do it
            server.forget(device_name)
            print("done.")

    @cli.autoswitch(help="do it, even if related data will be lost")
    def force(self):
        self._force = True


@WalTDevice.subcommand("config")
class WalTDeviceConfig(WalTApplication):
    """get or set devices configuration"""

    ORDERING = 6

    def main(self, device_set: SET_OF_DEVICES, *configuration: DEVICE_CONFIG_PARAM):
        with ClientToServerLink() as server:
            device_set = server.develop_device_set(device_set)
            if device_set is None:
                return
            if len(configuration) > 0:
                if not WalTDevice.confirm_devices_not_owned(server, device_set):
                    return
                server.set_device_config(device_set, configuration)
            else:
                # no settings specified => list current settings
                server.get_device_config(device_set)
