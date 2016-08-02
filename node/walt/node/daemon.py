#!/usr/bin/env python

import rpyc
from plumbum import cli
from walt.common.daemon import WalTDaemon
from walt.common.nodetypes import get_node_type_from_mac_address
from walt.common.tools import get_mac_address
from walt.common.constants import WALT_NODE_DAEMON_PORT
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.devices.fake import Fake
from walt.common.evloop import EventLoop
from walt.common.service import RPyCService
from walt.node.tools import lookup_server_ip
from walt.node.logs import LogsFifoServer
from walt.common.api import api, api_expose_method
from walt.common.versions import UPLOAD

WALT_NODE_NETWORK_INTERFACE = "eth0"

@RPyCService
@api
class WalTNodeService(object):
    ALIASES=("WalT_Node_Service",)
    def __init__(self, node_cls):
        self.node_cls = node_cls

    @api_expose_method
    def blink(self, blink_status):
        self.node_cls.blink(blink_status)

class NodeToServerLink(object):
    def __init__(self, server_ip = None):
        self.server_ip = server_ip
    def __enter__(self):
        if self.server_ip == None:
            self.server_ip = lookup_server_ip()
        self.conn = rpyc.connect(
                self.server_ip,
                WALT_SERVER_DAEMON_PORT)
        return self.conn.root.ns
    def __exit__(self, type, value, traceback):
        self.conn.close()

class WalTNodeDaemon(WalTDaemon):
    """WalT (wireless testbed) node daemon."""
    VERSION = 'node v' + str(UPLOAD)
    fake = cli.Flag("--fake", default = False,
            help = "Fake mode, for simulation")

    def getParameters(self):
        return dict(service_cl = WalTNodeService(self.node_cls),
                    port = WALT_NODE_DAEMON_PORT,
                    ev_loop = WalTNodeDaemon.ev_loop)

    def init(self):
        server_ip = None
        if self.fake:
            self.node_cls = Fake
            server_ip = '127.0.0.1'
        else:
            mac = get_mac_address(WALT_NODE_NETWORK_INTERFACE)
            self.node_cls = get_node_type_from_mac_address(mac)
            if self.node_cls == None:
                raise RuntimeError(
                    'Mac address does not match any known WalT node hardware.')
        with NodeToServerLink(server_ip) as server:
            server.node_bootup_event()

def run():
    ev_loop = EventLoop()
    logs_fifo_server = LogsFifoServer()
    logs_fifo_server.join_event_loop(ev_loop)
    WalTNodeDaemon.ev_loop = ev_loop
    WalTNodeDaemon.run()

if __name__ == "__main__":
    run()

