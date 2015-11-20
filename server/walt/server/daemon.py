#!/usr/bin/env python

import rpyc, sys, datetime, cPickle as pickle
import walt.server as server
from walt.server.network import setup
from walt.server.tools import AutoCleaner
from walt.server.ui.manager import UIManager
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
        self.server = server.instance
        self.images = server.instance.images
        self.devices = server.instance.devices
        self.nodes = server.instance.nodes
        self.logs = server.instance.logs

    def on_connect(self):
        self._client = self._conn.root

    def on_disconnect(self):
        self._client = None

    def exposed_device_rescan(self):
        self.server.device_rescan(self._client)

    def exposed_device_tree(self):
        return self.devices.topology.tree()

    def exposed_device_show(self):
        return self.devices.topology.show()

    def exposed_show_nodes(self, show_all):
        return self.nodes.show(self._client, show_all)

    def exposed_get_reachable_nodes_ip(self, node_set):
        return self.nodes.get_reachable_nodes_ip(
                        self._client, node_set)

    def exposed_get_device_ip(self, device_name):
        return self.devices.get_device_ip(
                        self._client, device_name)

    def exposed_get_node_ip(self, node_name):
        return self.nodes.get_node_ip(
                        self._client, node_name)

    def exposed_blink(self, node_name, blink_status):
        node_ip = self.nodes.get_reachable_node_ip(
                        self._client, node_name)
        if node_ip == None:
            return False # error was already reported
        with ServerToNodeLink(node_ip, self._client) as node_service:
            node_service.blink(blink_status)
        return True

    def exposed_parse_set_of_nodes(self, node_set):
        nodes = self.nodes.parse_node_set(self._client, node_set)
        if nodes:
            return [n.name for n in nodes]

    def exposed_includes_nodes_not_owned(self, node_set, warn):
        return self.nodes.includes_nodes_not_owned(self._client, node_set, warn)

    def exposed_poweroff(self, node_set, warn_unknown_topology):
        return self.nodes.setpower(self._client, node_set, False, warn_unknown_topology)

    def exposed_poweron(self, node_set, warn_unknown_topology):
        return self.nodes.setpower(self._client, node_set, True, warn_unknown_topology)

    def exposed_validate_node_cp(self, src, dst):
        return self.nodes.validate_cp(self._client, src, dst)

    def exposed_wait_for_nodes(self, q, node_set):
        self.nodes.wait(self._client, q, node_set)

    def exposed_rename(self, old_name, new_name):
        self.server.rename_device(self._client, old_name, new_name)

    def exposed_has_image(self, image_tag):
        return self.images.has_image(self._client, image_tag)

    def exposed_set_image(self, node_set, image_tag, warn_unknown_topology):
        self.server.set_image(self._client, node_set, image_tag, warn_unknown_topology)

    def exposed_is_device_reachable(self, device_name):
        return self.devices.is_reachable(self._client, device_name)

    def exposed_count_logs(self, history, **kwargs):
        unpickled_history = (pickle.loads(e) if e else None for e in history)
        return self.server.db.count_logs(history = unpickled_history, **kwargs)

    def exposed_forget(self, device_name):
        self.server.forget_device(device_name)

    def exposed_fix_image_owner(self, other_user):
        return self.images.fix_owner(self._client, other_user)

    def exposed_search_images(self, q, keyword):
        self.images.search(self._client, q, keyword)

    def exposed_clone_image(self, q, clonable_link, force=False):
        self.images.clone(requester = self._client,
                          q = q,
                          clonable_link = clonable_link,
                          force = force)

    def exposed_show_images(self):
        return self.images.show(self._client.username)

    def exposed_create_image_shell_session(self, image_tag):
        return self.images.create_shell_session(self._client, image_tag)

    def exposed_remove_image(self, image_tag):
        self.images.remove(self._client, image_tag)

    def exposed_rename_image(self, image_tag, new_tag):
        self.images.rename(self._client, image_tag, new_tag)

    def exposed_duplicate_image(self, image_tag, new_tag):
        self.images.duplicate(self._client, image_tag, new_tag)

    def exposed_validate_image_cp(self, src, dst):
        return self.images.validate_cp(self._client, src, dst)

    def exposed_node_bootup_event(self):
        node_ip, node_port = self._conn._config['endpoints'][1]
        self.devices.node_bootup_event(node_ip)
        node_name = self.devices.get_name_from_ip(node_ip)
        self.nodes.node_bootup_event(node_name)

    def exposed_add_checkpoint(self, cp_name, pickled_date):
        date = None
        if pickled_date:
            date = pickle.loads(pickled_date)
        self.logs.add_checkpoint(self._client, cp_name, date)

    def exposed_remove_checkpoint(self, cp_name):
        self.logs.remove_checkpoint(self._client, cp_name)

    def exposed_list_checkpoints(self):
        self.logs.list_checkpoints(self._client)

    def exposed_get_pickled_time(self):
        return pickle.dumps(datetime.datetime.now())

    def exposed_get_pickled_checkpoint_time(self, cp_name):
        return self.logs.get_pickled_checkpoint_time(self._client, cp_name)

class WalTServerDaemon(WalTDaemon):
    """WalT (wireless testbed) server daemon."""
    VERSION = WALT_SERVER_DAEMON_VERSION

    def getParameters(self):
        return dict(
                service_cl = PlatformService,
                port = WALT_SERVER_DAEMON_PORT,
                ev_loop = server.instance.ev_loop)

    def init_end(self):
        server.instance.ui.set_status('Ready.')

def run():
    ui = UIManager()
    if setup.setup_needed(ui):
        setup.setup(ui)
    myserver = server.Server(ui)
    with AutoCleaner(myserver) as server.instance:
        myserver.update()
        WalTServerDaemon.run()

if __name__ == "__main__":
    run()

