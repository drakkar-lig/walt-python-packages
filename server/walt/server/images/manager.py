from docker import Client
from walt.server.images.shell import ImageShellSessionStore
from walt.server.images.search import search
from walt.server.images.clone import clone
from walt.server.images.publish import publish
from walt.server.images.show import show
from walt.server.images.rename import rename
from walt.server.images.remove import remove
from walt.server.images.duplicate import duplicate
from walt.server.transfer import validate_cp
from walt.server.images.fixowner import fix_owner
from walt.server.images.store import NodeImageStore

# About terminology: See comment about it in image.py.

class NodeImageManager(object):
    def __init__(self, db, blocking_manager, dhcpd, docker):
        self.db = db
        self.blocking = blocking_manager
        self.dhcpd = dhcpd
        self.docker = docker
        self.store = NodeImageStore(self.docker, self.db)
        self.shells = ImageShellSessionStore(self.docker, self.store)
    def update(self):
        self.store.refresh()
        self.store.update_image_mounts()
    def search(self, requester, q, keyword):
        search(q, self.blocking, self.docker, requester, keyword)
    def clone(self, **kwargs):
        clone(blocking = self.blocking,
              docker = self.docker,
              image_store = self.store,
              **kwargs)
    def publish(self, **kwargs):
        publish(blocking = self.blocking,
              docker = self.docker,
              image_store = self.store,
              **kwargs)
    def show(self, username):
        return show(self.store, username)
    def rename(self, requester, image_tag, new_tag):
        rename(self.store, self.docker, requester, image_tag, new_tag)
    def remove(self, requester, image_tag):
        remove(self.store, self.docker, requester, image_tag)
    def duplicate(self, requester, image_tag, new_tag):
        duplicate(self.store, self.docker, requester, image_tag, new_tag)
    def validate_cp(self, requester, src, dst):
        return validate_cp("image", self, requester, src, dst)
    def validate_cp_entity(self, requester, image_tag):
        return self.has_image(requester, image_tag)
    def get_cp_entity_filesystem(self, requester, image_tag):
        return self.store.get_user_image_from_tag(requester, image_tag).filesystem
    def get_cp_entity_attrs(self, requester, image_tag):
        return dict(image_tag=image_tag)
    def fix_owner(self, requester, other_user):
        fix_owner(self.store, self.docker, requester, other_user)
    def cleanup(self):
        # give up image shell sessions
        self.shells.cleanup()
        # un-mount images
        self.store.cleanup()
    def has_image(self, requester, image_tag):
        if image_tag == 'default':
            return True
        else:
            return self.store.get_user_image_from_tag(requester, image_tag) != None
    def set_image(self, requester, node_macs, image_tag):
        # if image tag is specified, let's get its fullname
        if image_tag != 'default':
            image = self.store.get_user_image_from_tag(requester, image_tag)
            if image == None:
                return False
            image_fullname = image.fullname
        for node_mac in node_macs:
            # if the 'default' keyword was specified, we might have to deploy
            # different images depending of the type of each WalT node.
            # we compute the appropriate image fullname here.
            if image_tag == 'default':
                node_type = self.db.select_unique('devices', mac=node_mac).type
                image_fullname = self.store.get_default_image(node_type)
            # let's update the database about which node is mounting what
            self.db.update('nodes', 'mac',
                    mac=node_mac,
                    image=image_fullname)
        self.store.update_image_mounts()
        self.db.commit()
        self.dhcpd.update()
        return True
    def create_shell_session(self, requester, image_tag):
        return self.shells.create_session(requester, image_tag)

