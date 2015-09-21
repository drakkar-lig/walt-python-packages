#!/usr/bin/env python

import rpyc, time
from plumbum import cli
from walt.common.daemon import WalTDaemon
from walt.common.nodetypes import get_node_type_from_mac_address
from walt.common.tools import get_mac_address
from walt.common.constants import WALT_NODE_DAEMON_PORT
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.devices.fake import Fake
from walt.common.evloop import EventLoop
from walt.node.tools import lookup_server_ip
from walt.node.logs import LogsFifoServer

WALT_NODE_DAEMON_VERSION = 0.1
WALT_NODE_NETWORK_INTERFACE = "eth0"

class WalTNodeService(rpyc.Service):
    ALIASES=("WalT_Node_Service",)
    def on_connect(self):
        self._client = self._conn.root

    def on_disconnect(self):
        self._client = None

    def exposed_blink(self, blink_status):
        WalTNodeService.NodeClass.blink(blink_status)

class NodeToServerLink:
    server_ip = None
    def __enter__(self):
        if NodeToServerLink.server_ip == None:
            NodeToServerLink.server_ip = lookup_server_ip()
        self.conn = rpyc.connect(
                NodeToServerLink.server_ip,
                WALT_SERVER_DAEMON_PORT)
        return self.conn.root

    def __exit__(self, type, value, traceback):
        self.conn.close()

class WalTNodeDaemon(WalTDaemon):
    """WalT (wireless testbed) node daemon."""
    VERSION = WALT_NODE_DAEMON_VERSION
    fake = cli.Flag("--fake", default = False,
            help = "Fake mode, for simulation")

    def getParameters(self):
        return dict(service_cl = WalTNodeService,
                    port = WALT_NODE_DAEMON_PORT,
                    ev_loop = WalTNodeDaemon.ev_loop)

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
            server.node_bootup_event()

def run():
    ev_loop = EventLoop()
    logs_fifo_server = LogsFifoServer()
    logs_fifo_server.join_event_loop(ev_loop)
    WalTNodeDaemon.ev_loop = ev_loop
    WalTNodeDaemon.run()

if __name__ == "__main__":
    run()

