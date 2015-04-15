#!/usr/bin/env python

from walt.server.image import NodeImageRepository
from walt.server.platform import Platform
from walt.server.db import ServerDB

class Server(object):

    def __init__(self):
        self.db = ServerDB()
        self.platform = Platform(self.db)
        self.images = NodeImageRepository(self.db)
        self.images.update_image_mounts()

    def cleanup(self):
        self.images.cleanup()

