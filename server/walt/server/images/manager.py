from docker import Client
from walt.server.images.shell import ImageShellSessionStore
from walt.server.images.search import search
from walt.server.images.clone import clone
from walt.server.images.show import show
from walt.server.images.rename import rename
from walt.server.images.remove import remove
from walt.server.images.copy import copy
from walt.server.images.fixowner import fix_owner
from walt.server.images.store import NodeImageStore

# About terminology: See comment about it in image.py.

class NodeImageManager(object):
    def __init__(self, db, blocking_manager):
        self.db = db
        self.blocking = blocking_manager
        self.c = Client(base_url='unix://var/run/docker.sock', version='auto')
        self.images = NodeImageStore(self.c, self.db)
        self.shells = ImageShellSessionStore(self.c, self.images)
    def update(self):
        self.images.refresh()
        self.images.update_image_mounts()
    def search(self, requester, q, keyword):
        search(q, self.blocking, self.c, requester, keyword)
    def clone(self, requester, q, clonable_link, force):
        clone(q, self.blocking, self.c, requester, clonable_link, self.images, force)
    def show(self, username):
        return show(self.images, username)
    def rename(self, requester, image_tag, new_tag):
        rename(self.images, self.c, requester, image_tag, new_tag)
    def remove(self, requester, image_tag):
        remove(self.images, self.c, requester, image_tag)
    def copy(self, requester, image_tag, new_tag):
        copy(self.images, self.c, requester, image_tag, new_tag)
    def fix_owner(self, requester, other_user):
        fix_owner(self.images, self.c, requester, other_user)
    def cleanup(self):
        # give up image shell sessions
        self.shells.cleanup()
        # un-mount images
        self.images.cleanup()
    def has_image(self, requester, image_tag):
        return self.images.get_user_image_from_tag(requester, image_tag) != None
    def set_image(self, requester, node_mac, image_tag):
        image = self.images.get_user_image_from_tag(requester, image_tag)
        if image:
            self.db.update('nodes', 'mac',
                    mac=node_mac,
                    image=image.fullname)
            self.images.update_image_mounts()
            self.db.commit()
    def set_default(self, requester, image_tag):
        image = self.images.get_user_image_from_tag(requester, image_tag)
        if image:
            self.db.set_config(
                    CONFIG_ITEM_DEFAULT_IMAGE,
                    image.fullname)
            self.images.update_image_mounts()
            self.db.commit()
    def create_shell_session(self, requester, image_tag):
        return self.shells.create_session(requester, image_tag)

