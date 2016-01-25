from plumbum import cli
from walt.client.link import ClientToServerLink
from walt.client.interactive import run_device_ping

class WalTDevice(cli.Application):
    """management of WalT platform devices"""
    pass

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

