#!/usr/bin/env python

import rpyc
from plumbum import cli
from walt.common.daemon import WalTDaemon
from walt.common.devices.registry import get_node_cls_from_model
from walt.common.tools import get_kernel_bootarg
from walt.common.constants import WALT_NODE_DAEMON_PORT
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.devices.nodes.fake import Fake
from walt.common.evloop import EventLoop
from walt.common.apilink import ServerAPILink, APIService
from walt.node.tools import lookup_server_ip
from walt.node.logs import LogsFifoServer
from walt.common.api import api, api_expose_method
from walt.common.versions import UPLOAD

@APIService
@api
class WalTNodeService(object):
    ALIASES=("WalT_Node_Service",)
    def __init__(self, node_cls):
        self.node_cls = node_cls

    @api_expose_method
    def blink(self, blink_status):
        self.node_cls.blink(blink_status)

def get_node_cls_from_bootarg():
    node_model = get_kernel_bootarg('walt.node.model')
    if node_model == None:
        raise RuntimeError(
            'Missing kernel bootarg: "walt.node.model"!')
    node_cls = get_node_cls_from_model(node_model)
    if node_cls == None:
        raise RuntimeError(
            'This image does not know how to handle the walt.node.model specified: "' \
                    + node_model + '"!')
    return node_cls

class NodeToServerLink(ServerAPILink):
    def __init__(self, server_ip = None):
        if server_ip == None:
            server_ip = lookup_server_ip()
        ServerAPILink.__init__(self, server_ip, 'NSAPI')

class WalTNodeDaemon(WalTDaemon):
    """WalT (wireless testbed) node daemon."""
    VERSION = 'node v' + str(UPLOAD)
    fake = cli.Flag("--fake", default = False,
            help = "Fake mode, for simulation")

    def getParameters(self):
        if self.fake:
            node_cls = Fake
        else:
            node_cls = get_node_cls_from_bootarg()
        return dict(service_cl = WalTNodeService(node_cls),
                    port = WALT_NODE_DAEMON_PORT,
                    ev_loop = WalTNodeDaemon.ev_loop)

    def init(self):
        server_ip = None
        if self.fake:
            self.node_cls = Fake
            server_ip = '127.0.0.1'
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

