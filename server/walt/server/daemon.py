#!/usr/bin/env python

import rpyc, sys
import walt.server as server
from walt.server.network import setup
from walt.server.tools import AutoCleaner
from walt.common.daemon import WalTDaemon
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

    def __init__(self, *args, **kwargs):
        rpyc.Service.__init__(self, *args, **kwargs)
        self.platform = server.instance.platform
        self.images = server.instance.images
        self.server = server.instance

    def on_connect(self):
        self._client = self._conn.root

    def on_disconnect(self):
        self._client = None

    def exposed_update(self):
        self.platform.update(self._client)

    def exposed_describe(self, details=False):
        return self.platform.describe(details)

    def exposed_list_nodes(self):
        return self.platform.list_nodes()

    def exposed_get_reachable_node_ip(self, node_name):
        return self.platform.topology.get_reachable_node_ip(
                        self._client, node_name)

    def exposed_blink(self, node_name, duration):
        node_ip = self.platform.topology.get_reachable_node_ip(
                        self._client, node_name)
        if node_ip == None:
            return # error was already reported
        with ServerToNodeLink(node_ip, self._client) as node_service:
            node_service.blink(duration)

    def exposed_poweroff(self, node_name):
        return self.platform.setpower(self._client, node_name, False)

    def exposed_poweron(self, node_name):
        return self.platform.setpower(self._client, node_name, True)

    def exposed_rename(self, old_name, new_name):
        self.platform.rename_device(self._client, old_name, new_name)

    def exposed_register_node(self):
        node_ip, node_port = self._conn._config['endpoints'][1]
        self.platform.register_node(node_ip)

    def exposed_has_image(self, image_name):
        return self.images.has_image(self._client, image_name)

    def exposed_set_image(self, node_name, image_name):
        self.server.set_image(self._client, node_name, image_name)

    def exposed_list_images(self):
        return self.images.describe()

    def exposed_set_default_image(self, image_name):
        self.server.set_default_image(self._client, image_name)

    def exposed_create_modify_image_session(self, image_name):
        return self.images.create_modify_session(self._client, image_name)

    def exposed_remove_image(self, image_name):
        self.images.remove(self._client, image_name)

    def exposed_rename_image(self, image_name, new_name):
        self.images.rename(self._client, image_name, new_name)

class WalTServerDaemon(WalTDaemon):
    """WalT (wireless testbed) server daemon."""
    VERSION = WALT_SERVER_DAEMON_VERSION

    def getParameters(self):
        return dict(
                service_cl = PlatformService,
                port = WALT_SERVER_DAEMON_PORT,
                ev_loop = server.instance.ev_loop)

def run():
    if setup.setup_needed():
        setup.setup()
    with AutoCleaner(server.Server) as server.instance:
        server.instance.update()
        WalTServerDaemon.run()

if __name__ == "__main__":
    run()

