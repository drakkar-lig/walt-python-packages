from plumbum import cli
from walt.client.link import ClientToServerLink
from walt.client.interactive import run_device_ping
from walt.client.device.admin import WalTDeviceAdmin
from walt.client.tools import confirm
from walt.common.tools import deserialize_ordered_dict
from walt.client.application import WalTCategoryApplication, WalTApplication

class WalTDevice(WalTCategoryApplication):
    """management of WalT platform devices"""
    @staticmethod
    def confirm_devices_not_owned(server, device_set):
        not_owned = server.includes_devices_not_owned(device_set, warn=True)
        if not_owned == None:
            return False
        if not_owned == True:
            if not confirm():
                return False
        return True

@WalTDevice.subcommand("tree")
class WalTDeviceTree(WalTApplication):
    """print the network structure of the platform"""
    _all = False # default
    def main(self):
        with ClientToServerLink() as server:
            print server.device_tree(self._all)
    @cli.autoswitch(help='show all devices detected')
    def all(self):
        self._all = True

@WalTDevice.subcommand("show")
class WalTDeviceShow(WalTApplication):
    """print details about devices involved in the platform"""
    def main(self):
        with ClientToServerLink() as server:
            print server.device_show()

@WalTDevice.subcommand("rescan")
class WalTDeviceRescan(WalTApplication):
    """rescan the network devices involved in the platform"""
    def main(self, device_set='server,explorable-switches'):
        with ClientToServerLink() as server:
            server.device_rescan(device_set)

@WalTDevice.subcommand("rename")
class WalTRenameDevice(WalTApplication):
    """rename a device"""
    def main(self, old_name, new_name):
        with ClientToServerLink() as server:
            server.rename(old_name, new_name)

@WalTDevice.subcommand("ping")
class WalTDevicePing(WalTApplication):
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
If this is what you want, run 'walt device forget --force %s'."""

MSG_USE_WALT_NODE_REMOVE = """\
%(node)s is a virtual node. Use 'walt node remove %(node)s' instead."""

@WalTDevice.subcommand("forget")
class WalTDeviceForget(WalTApplication):
    """let the WalT system forget about an obsolete device"""
    _force = False # default
    def main(self, device_name):
        with ClientToServerLink() as server:
            # check if server knows this device
            device_info = server.get_device_info(device_name)
            if device_info == None:
                return  # issue already reported
            device_info = deserialize_ordered_dict(device_info)
            if device_info['type'] == 'node' and device_info['virtual']:
                print MSG_USE_WALT_NODE_REMOVE % dict(node = device_name)
                return
            if not self._force:
                logs_cnt = server.count_logs(
                        history = (None, None),
                        senders = set([device_name]))
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

# this one has much code and has its own module
WalTDevice.subcommand("admin", WalTDeviceAdmin)

@WalTDevice.subcommand("config")
class WalTDeviceConfig(WalTApplication):
    """Set devices configuration"""
    def main(self, device_set, *configuration):
        with ClientToServerLink() as server:
            device_set = server.develop_device_set(device_set)
            if device_set is None:
                return
            if not WalTDevice.confirm_devices_not_owned(server, device_set):
                return
            server.set_device_config(device_set, configuration)
