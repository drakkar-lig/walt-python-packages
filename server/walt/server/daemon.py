#!/usr/bin/env python

import rpyc, sys, datetime, cPickle as pickle

from walt.server.server import Server
from walt.server.network import setup
from walt.server.network.tools import set_server_ip
from walt.server.tools import AutoCleaner
from walt.server.ui.manager import UIManager
from walt.common.crypto.dh import DHPeer
from walt.common.daemon import WalTDaemon
from walt.common.versions import API_VERSIONING, UPLOAD
from walt.common.constants import           \
                 WALT_SERVER_DAEMON_PORT,   \
                 WALT_NODE_DAEMON_PORT
from walt.common.api import api, api_expose_method

WALT_SERVER_DAEMON_VERSION = 'server v' + str(UPLOAD)

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

@api
class PlatformService(rpyc.Service):
    ALIASES=("WalT_Platform",)

    def __init__(self, *args, **kwargs):
        rpyc.Service.__init__(self, *args, **kwargs)
        self.server = Server.instance
        self.images = Server.instance.images
        self.devices = Server.instance.devices
        self.nodes = Server.instance.nodes
        self.logs = Server.instance.logs

    def on_connect(self):
        self._client = self._conn.root

    def on_disconnect(self):
        self._client = None
    @api_expose_method
    def get_version(self):
        return WALT_SERVER_DAEMON_VERSION

    @api_expose_method
    def get_API_versions(self):
        return(API_VERSIONING['SERVER'][0], API_VERSIONING['CLIENT'][0])

    @api_expose_method
    def device_rescan(self):
        self.server.device_rescan(self._client)

    @api_expose_method
    def device_tree(self):
        return self.devices.topology.tree()

    @api_expose_method
    def device_show(self):
        return self.devices.topology.show()

    @api_expose_method
    def show_nodes(self, show_all):
        return self.nodes.show(self._client, show_all)

    @api_expose_method
    def get_reachable_nodes_ip(self, node_set):
        return self.nodes.get_reachable_nodes_ip(
                        self._client, node_set)

    @api_expose_method
    def get_device_ip(self, device_name):
        return self.devices.get_device_ip(
                        self._client, device_name)

    @api_expose_method
    def get_node_ip(self, node_name):
        return self.nodes.get_node_ip(
                        self._client, node_name)

    @api_expose_method
    def blink(self, node_name, blink_status):
        nodes_ip = self.nodes.get_reachable_nodes_ip(
                        self._client, node_name)
        if len(nodes_ip) == 0:
            return False # error was already reported
        with ServerToNodeLink(nodes_ip[0], self._client) as node_service:
            node_service.blink(blink_status)
        return True

    @api_expose_method
    def parse_set_of_nodes(self, node_set):
        nodes = self.nodes.parse_node_set(self._client, node_set)
        if nodes:
            return [n.name for n in nodes]

    @api_expose_method
    def includes_nodes_not_owned(self, node_set, warn):
        return self.nodes.includes_nodes_not_owned(self._client, node_set, warn)

    @api_expose_method
    def poweroff(self, node_set, warn_unknown_topology):
        return self.nodes.setpower(self._client, node_set, False, warn_unknown_topology)

    @api_expose_method
    def poweron(self, node_set, warn_unknown_topology):
        return self.nodes.setpower(self._client, node_set, True, warn_unknown_topology)

    @api_expose_method
    def validate_node_cp(self, src, dst):
        return self.nodes.validate_cp(self._client, src, dst)

    @api_expose_method
    def wait_for_nodes(self, q, node_set):
        self.nodes.wait(self._client, q, node_set)

    @api_expose_method
    def rename(self, old_name, new_name):
        self.server.rename_device(self._client, old_name, new_name)

    @api_expose_method
    def has_image(self, image_tag):
        return self.images.has_image(self._client, image_tag)

    @api_expose_method
    def set_image(self, node_set, image_tag, warn_unknown_topology):
        self.server.set_image(self._client, node_set, image_tag, warn_unknown_topology)

    @api_expose_method
    def is_device_reachable(self, device_name):
        return self.devices.is_reachable(self._client, device_name)

    @api_expose_method
    def count_logs(self, history, **kwargs):
        unpickled_history = (pickle.loads(e) if e else None for e in history)
        return self.server.db.count_logs(history = unpickled_history, **kwargs)

    @api_expose_method
    def forget(self, device_name):
        self.server.forget_device(device_name)

    @api_expose_method
    def fix_image_owner(self, other_user):
        return self.images.fix_owner(self._client, other_user)

    @api_expose_method
    def search_images(self, q, keyword):
        self.images.search(self._client, q, keyword)

    @api_expose_method
    def clone_image(self, q, clonable_link, force=False, auto_update=False):
        self.images.clone(requester = self._client,
                          q = q,
                          clonable_link = clonable_link,
                          force = force,
                          auto_update = auto_update)

    @api_expose_method
    def get_dh_peer(self):
        return DHPeer()

    @api_expose_method
    def publish_image(self, q, auth_conf, image_tag):
        self.images.publish(requester = self._client,
                          q = q,
                          auth_conf = auth_conf,
                          image_tag = image_tag)

    @api_expose_method
    def docker_login(self, auth_conf):
        return self.server.docker.login(auth_conf, self._client.stdout)

    @api_expose_method
    def show_images(self):
        return self.images.show(self._client.username)

    @api_expose_method
    def create_image_shell_session(self, image_tag):
        return self.images.create_shell_session(self._client, image_tag)

    @api_expose_method
    def remove_image(self, image_tag):
        self.images.remove(self._client, image_tag)

    @api_expose_method
    def rename_image(self, image_tag, new_tag):
        self.images.rename(self._client, image_tag, new_tag)

    @api_expose_method
    def duplicate_image(self, image_tag, new_tag):
        self.images.duplicate(self._client, image_tag, new_tag)

    @api_expose_method
    def update_image(self, image_tag):
        self.images.update_walt_software(self._client, image_tag)

    @api_expose_method
    def validate_image_cp(self, src, dst):
        return self.images.validate_cp(self._client, src, dst)

    @api_expose_method
    def node_bootup_event(self):
        node_ip, node_port = self._conn._config['endpoints'][1]
        self.devices.node_bootup_event(node_ip)
        node_name = self.devices.get_name_from_ip(node_ip)
        self.nodes.node_bootup_event(node_name)

    @api_expose_method
    def add_checkpoint(self, cp_name, pickled_date):
        date = None
        if pickled_date:
            date = pickle.loads(pickled_date)
        self.logs.add_checkpoint(self._client, cp_name, date)

    @api_expose_method
    def remove_checkpoint(self, cp_name):
        self.logs.remove_checkpoint(self._client, cp_name)

    @api_expose_method
    def list_checkpoints(self):
        self.logs.list_checkpoints(self._client)

    @api_expose_method
    def get_pickled_time(self):
        return pickle.dumps(datetime.datetime.now())

    @api_expose_method
    def get_pickled_checkpoint_time(self, cp_name):
        return self.logs.get_pickled_checkpoint_time(self._client, cp_name)

class WalTServerDaemon(WalTDaemon):
    """WalT (wireless testbed) server daemon."""
    VERSION = WALT_SERVER_DAEMON_VERSION

    def getParameters(self):
        return dict(
                service_cl = PlatformService,
                port = WALT_SERVER_DAEMON_PORT,
                ev_loop = Server.instance.ev_loop)

    def init_end(self):
        Server.instance.ui.set_status('Ready.')

def notify_systemd():
    try:
        import sdnotify
        sdnotify.SystemdNotifier().notify("READY=1")
    except:
        pass

def run():
    ui = UIManager()
    myserver = Server(ui)
    # set ip on WalT network (eth0.1)
    set_server_ip()
    myserver.dhcpd.update(force=True)
    setup.setup(ui)
    notify_systemd()
    with AutoCleaner(myserver) as Server.instance:
        myserver.update()
        WalTServerDaemon.run()

if __name__ == "__main__":
    run()

