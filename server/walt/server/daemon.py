#!/usr/bin/env python

import rpyc, sys
from walt.common.daemon import WalTDaemon
from walt.server.topology import PoEPlatform
from walt.common.constants import           \
                 WALT_SERVER_DAEMON_PORT,   \
                 WALT_NODE_DAEMON_PORT

WALT_SERVER_DAEMON_VERSION = 0.1

class ClientMirroringService(rpyc.Service):
    services_per_node = {}

    def on_connect(self):
        node_id = id(self._conn.root)
        self._node_id = node_id
        ClientMirroringService.services_per_node[node_id] = self

    def on_disconnect(self):
        del ClientMirroringService.services_per_node[self._node_id]

    def __del__(self):
        self._client = None

    def register_client(self, client):
        self._client = client

    @staticmethod
    def link_node_to_client(node, client): 
        service = ClientMirroringService.services_per_node[id(node)]
        service.register_client(client)

    # forward all other method accesses to self._client
    def __getattr__(self, attr_name):
        return getattr(self._client, attr_name)

class ServerToNodeLink:
    def __init__(self, ip_address, client = None):
        self.node_ip = ip_address
        self.client = client

    def __enter__(self):
        if self.client:
            self.conn = rpyc.connect(self.node_ip, WALT_NODE_DAEMON_PORT,
                            service = ClientMirroringService)
            node_service = self.conn.root
            ClientMirroringService.link_node_to_client(node_service, self.client)
        else:
            self.conn = rpyc.connect(self.node_ip, WALT_NODE_DAEMON_PORT)
        return self.conn.root

    def __exit__(self, type, value, traceback):
        self.conn.close()

class PlatformService(rpyc.Service):
    ALIASES=("WalT_Platform",)
    def on_connect(self):
        self._client = self._conn.root
    
    def on_disconnect(self):
        self._client = None
    
    def exposed_update(self):
        PlatformService.platform.update(self._client)

    def exposed_describe(self):
        return PlatformService.platform.describe()

    def exposed_blink(self, node_ip, duration):
        with ServerToNodeLink(node_ip, self._client) as node_service:
            node_service.blink(duration)

    def exposed_reboot(self, ip_address):
        PlatformService.platform.reboot_node(self._client, ip_address)

class WalTServerDaemon(WalTDaemon):
    """WalT (wireless testbed) server daemon."""
    VERSION = WALT_SERVER_DAEMON_VERSION

    def getRPyCServiceClassAndPort(self):
        return (PlatformService, WALT_SERVER_DAEMON_PORT)

    def init(self):
        PlatformService.platform = PoEPlatform()

def run():
    WalTServerDaemon.run()

if __name__ == "__main__":
    run()

