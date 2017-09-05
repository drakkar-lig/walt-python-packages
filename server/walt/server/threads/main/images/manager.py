from walt.server.threads.main.images.shell import ImageShellSession
from walt.server.threads.main.images.search import search
from walt.server.threads.main.images.clone import clone
from walt.server.threads.main.images.publish import publish
from walt.server.threads.main.images.show import show
from walt.server.threads.main.images.rename import rename
from walt.server.threads.main.images.remove import remove
from walt.server.threads.main.images.duplicate import duplicate
from walt.server.threads.main.transfer import validate_cp
from walt.server.threads.main.images.fixowner import fix_owner
from walt.server.threads.main.images.store import NodeImageStore
from walt.server.threads.main.images.boot.bootfiles import update_bootfiles
from walt.server.threads.main.network import tftp
from walt.common.tools import format_sentence_about_nodes

# About terminology: See comment about it in image.py.
MSG_BOOT_DEFAULT_IMAGE = """\
%s will now boot its(their) default image (other users will see it(they) is(are) 'free')."""

class NodeImageManager(object):
    def __init__(self, db, blocking_manager, dhcpd, docker):
        self.db = db
        self.blocking = blocking_manager
        self.dhcpd = dhcpd
        self.docker = docker
        self.store = NodeImageStore(self.docker, self.db)
    def update(self, startup = False):
        update_bootfiles()
        self.store.refresh(startup)
        self.store.update_image_mounts()
    def search(self, requester, task, keyword):
        return search(self.blocking, requester, task, keyword)
    def clone(self, requester, task, **kwargs):
        return clone(self.blocking, requester, task, **kwargs)
    def publish(self, requester, task, image_tag, **kwargs):
        return publish(self.store, self.blocking, requester, task, image_tag, **kwargs)
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
        # un-mount images
        self.store.cleanup()
    def has_image(self, requester, image_tag):
        if image_tag == 'default':
            return True
        else:
            return self.store.get_user_image_from_tag(requester, image_tag) != None
    def set_image(self, requester, nodes, image_tag):
        # if image tag is specified, let's get its fullname
        if image_tag != 'default':
            image = self.store.get_user_image_from_tag(requester, image_tag)
            if image == None:
                return False
            image_fullnames = { node.mac: image.fullname for node in nodes }
        else:
            image_fullnames = {}
            # since the 'default' keyword was specified, we might have to deploy
            # different images depending on the type of each WalT node.
            # we compute the appropriate image fullname here.
            for node in nodes:
                image_fullnames[node.mac] = self.store.get_default_image(node.model)
        # let's update the database about which node is mounting what
        for node_mac, image_fullname in image_fullnames.items():
            self.db.update('nodes', 'mac',
                    mac=node_mac,
                    image=image_fullname)
        self.store.update_image_mounts(requester = requester)
        tftp.update(self.db)
        self.db.commit()
        self.dhcpd.update()
        # inform requester
        if image_tag == 'default':
            sentence = MSG_BOOT_DEFAULT_IMAGE
        else:
            sentence = '%s will now boot ' + image_tag + '.'
        requester.stdout.write(format_sentence_about_nodes(
            sentence, [n.name for n in nodes]) + '\n')
        return True
    def create_shell_session(self, requester, image_tag, task_label):
        image = self.store.get_user_image_from_tag(requester, image_tag)
        if image is None:
            return None
        if image.task_label:
            requester.stderr.write('Cannot open image %s because a %s is already running.\n' % \
                                    (image_tag, image.task_label))
            return None
        session = ImageShellSession(self.store, image.fullname, task_label)
        return session

