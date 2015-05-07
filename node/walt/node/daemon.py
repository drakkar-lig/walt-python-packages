#!/usr/bin/env python

import rpyc, time
from plumbum import cli
from walt.common.daemon import WalTDaemon
from walt.common.nodetypes import get_node_type_from_mac_address
from walt.common.tools import get_mac_address
from walt.common.constants import WALT_NODE_DAEMON_PORT
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.devices.fake import Fake

WALT_NODE_DAEMON_VERSION = 0.1
WALT_NODE_NETWORK_INTERFACE = "eth0"

class WalTNodeService(rpyc.Service):
    ALIASES=("WalT_Node_Service",)
    def on_connect(self):
        self._client = self._conn.root

    def on_disconnect(self):
        self._client = None

    def exposed_blink(self, duration):
        WalTNodeService.NodeClass.blink(True)
        self._client.write_stdout('blinking for %ds... ' % duration)
        time.sleep(duration)
        WalTNodeService.NodeClass.blink(False)
        self._client.write_stdout('done.\n')

class NodeToServerLink:
    server_ip = None
    def __enter__(self):
        if NodeToServerLink.server_ip == None:
            self.lookup_server_ip()
        self.conn = rpyc.connect(
                NodeToServerLink.server_ip,
                WALT_SERVER_DAEMON_PORT)
        return self.conn.root

    def __exit__(self, type, value, traceback):
        self.conn.close()

    def lookup_server_ip(self):
        with open('/proc/cmdline') as f:
            for t in [ elem.split('=') for elem in f.read().split() ]:
                if t[0] == 'nfs_server':
                    NodeToServerLink.server_ip = t[1]

class WalTNodeDaemon(WalTDaemon):
    """WalT (wireless testbed) node daemon."""
    VERSION = WALT_NODE_DAEMON_VERSION
    fake = cli.Flag("--fake", default = False, 
            help = "Fake mode, for simulation")

    def getRPyCServiceClassAndPort(self):
        return (WalTNodeService, WALT_NODE_DAEMON_PORT)

    def init(self):
        if self.fake:
            node_type = Fake
            NodeToServerLink.server_ip = '127.0.0.1'
        else:
            mac = get_mac_address(WALT_NODE_NETWORK_INTERFACE)
            node_type = get_node_type_from_mac_address(mac)
            if node_type == None:
                raise RuntimeError(
                    'Mac address does not match any known WalT node hardware.')
        WalTNodeService.NodeClass = node_type
        with NodeToServerLink() as server:
            server.register_node()

def run():
    WalTNodeDaemon.run()

if __name__ == "__main__":
    run()

