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
        self.images.update_image_mounts()
        self.dhcpd = DHCPServer(self.db)
        self.dhcpd.update()

    def cleanup(self):
        self.images.cleanup()


