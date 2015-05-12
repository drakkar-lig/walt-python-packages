#!/usr/bin/env python

from walt.server.image import NodeImageRepository
from walt.server.platform import Platform
from walt.server.db import ServerDB
from walt.server.network.dhcpd import DHCPServer

class Server(object):

    def __init__(self):
        self.db = ServerDB()
        self.platform = Platform(self.db)
        self.images = NodeImageRepository(self.db)
        self.dhcpd = DHCPServer(self.db)

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
        mac = node_info['mac']
        self.images.set_image(requester, mac, image_name)

