#!/usr/bin/env python

from walt.common.io import EventLoop
from walt.common.prompt import RemotePrompt
from walt.server.image import NodeImageRepository
from walt.server.platform import Platform
from walt.server.db import ServerDB
from walt.server.logs import LogsManager
from walt.server.network.dhcpd import DHCPServer

class Server(object):

    def __init__(self):
        self.ev_loop = EventLoop()
        self.db = ServerDB()
        self.platform = Platform(self.db)
        self.images = NodeImageRepository(self.db)
        self.dhcpd = DHCPServer(self.db)
        self.logs = LogsManager(self.db, self.ev_loop)

    def update(self):
        # ensure the dhcp server is running,
        # otherwise the switches may have ip addresses
        # outside the WalT network, and we will not be able
        # to communicate with them when trying to update
        # the topology.
        self.dhcpd.update()
        # topology exploration
        self.platform.topology.update()
        # update dhcp again for any new device
        self.dhcpd.update()
        # mount images needed
        self.images.update_image_mounts()

    def cleanup(self):
        self.images.cleanup()

    def set_image(self, requester, node_name, image_name):
        node_info = self.platform.topology.get_node_info(
                        requester, node_name)
        if node_info == None:
            return # error already reported
        mac = node_info.mac
        self.images.set_image(requester, mac, image_name)

    def sql_prompt(self, rpyc_conn, client_handler):
        prompt = RemotePrompt('psql walt', rpyc_conn,
                                self.ev_loop, client_handler)
        prompt.start()
        return prompt
