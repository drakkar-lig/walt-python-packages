from walt.server.threads.main.images.shell import ImageShellSession
from walt.server.threads.main.images.search import search
from walt.server.threads.main.images.clone import clone
from walt.server.threads.main.images.publish import publish
from walt.server.threads.main.images.squash import squash
from walt.server.threads.main.images.metadata import update_hub_metadata
from walt.server.threads.main.images.show import show
from walt.server.threads.main.images.rename import rename
from walt.server.threads.main.images.remove import remove
from walt.server.threads.main.images.duplicate import duplicate
from walt.server.threads.main.transfer import validate_cp
from walt.server.threads.main.images.fixowner import fix_owner
from walt.server.threads.main.images.store import NodeImageStore
from walt.server.threads.main.network import tftp
from walt.common.tools import format_sentence, format_sentence_about_nodes

# About terminology: See comment about it in image.py.
MSG_BOOT_DEFAULT_IMAGE = """\
%s will now boot its(their) default image (other users will see it(they) is(are) 'free')."""
MSG_INCOMPATIBLE_MODELS = """\
Sorry, this image is not compatible with %s.
"""

class NodeImageManager(object):
    def __init__(self, db, blocking_manager, dhcpd, docker):
        self.db = db
        self.blocking = blocking_manager
        self.dhcpd = dhcpd
        self.docker = docker
        self.store = NodeImageStore(self.docker, self.db)
    def prepare(self):
        pass
    def update(self, startup = False):
        self.store.refresh(startup)
        self.store.update_image_mounts()
        tftp.update(self.db, self.store)
    def search(self, requester, task, keyword, tty_mode):
        return search(self.blocking, requester, task, keyword, tty_mode)
    def clone(self, requester, task, **kwargs):
        return clone(self.blocking, requester, task, **kwargs)
    def publish(self, requester, task, image_name, **kwargs):
        return publish(self.store, self.blocking, requester, task, image_name, **kwargs)
    def squash(self, requester, task_callback, image_name, confirmed):
        return squash(self.store, self.blocking, requester, task_callback, image_name, confirmed)
    def show(self, requester, refresh):
        return show(self.db, self.docker, self.store, requester, refresh)
    def rename(self, requester, image_name, new_name):
        rename(self.store, self.docker, requester, image_name, new_name)
    def remove(self, requester, image_name):
        remove(self.store, self.docker, requester, image_name)
    def duplicate(self, requester, image_name, new_name):
        duplicate(self.store, self.docker, requester, image_name, new_name)
    def validate_cp(self, requester, src, dst):
        return validate_cp("image", self, requester, src, dst)
    def validate_cp_entity(self, requester, image_name, index):
        if not self.has_image(requester, image_name, False):
            return 'FAILED'
        if index == 1:  # image is destination, it will be modified
            if self.store.warn_if_would_reboot_nodes(requester, image_name):
                return 'NEEDS_CONFIRM'
        return 'OK'
    def get_cp_entity_filesystem(self, requester, image_name):
        return self.store.get_user_image_from_name(requester, image_name).filesystem
    def get_cp_entity_attrs(self, requester, image_name):
        return dict(image_name=image_name)
    def fix_owner(self, requester, other_user):
        fix_owner(self.store, self.docker, requester, other_user)
    def cleanup(self):
        # un-mount images
        self.store.cleanup()
    def has_image(self, requester, image_name, default_allowed):
        if default_allowed and image_name == 'default':
            return True
        else:
            return self.store.get_user_image_from_name(requester, image_name) != None
    def set_image(self, requester, nodes, image_name):
        # if image tag is specified, let's get its fullname
        if image_name != 'default':
            image = self.store.get_user_image_from_name(requester, image_name)
            if image == None:
                return False
            image_compatible_models = set(image.get_node_models())
            node_models = set(node.model for node in nodes)
            incompatible_models = node_models - image_compatible_models
            if len(incompatible_models) > 0:
                sentence = format_sentence(MSG_INCOMPATIBLE_MODELS, incompatible_models,
                                None, 'node model', 'node models')
                requester.stderr.write(sentence)
                return False
            image_fullnames = { node.mac: image.fullname for node in nodes }
        else:
            image_fullnames = {}
            # since the 'default' keyword was specified, we might have to associate
            # different images depending on the type of each WalT node.
            # we compute the appropriate image fullname here.
            for node in nodes:
                image_fullnames[node.mac] = self.store.get_default_image_fullname(node.model)
        # let's update the database about which node is mounting what
        for node_mac, image_fullname in image_fullnames.items():
            self.db.update('nodes', 'mac',
                    mac=node_mac,
                    image=image_fullname)
        self.store.update_image_mounts(requester = requester)
        tftp.update(self.db, self.store)
        self.db.commit()
        self.dhcpd.update()
        # inform requester
        if image_name == 'default':
            sentence = MSG_BOOT_DEFAULT_IMAGE
        else:
            sentence = '%s will now boot ' + image_name + '.'
        requester.stdout.write(format_sentence_about_nodes(
            sentence, [n.name for n in nodes]) + '\n')
        return True
    def create_shell_session(self, requester, image_name, task_label):
        image = self.store.get_user_image_from_name(requester, image_name)
        if image is None:
            return None
        if not image.editable:
            requester.stderr.write(('Cannot open image %(image_name)s because it has already reached its max number of layers.\n' +
                                    '(tip: walt image squash %(image_name)s)\n') % dict(image_name = image_name))
            return None
        if image.task_label:
            requester.stderr.write('Cannot open image %s because a %s is already running.\n' % \
                                    (image_name, image.task_label))
            return None
        session = ImageShellSession(self.store, image, task_label)
        return session
    def update_hub_metadata(self, context, auth_conf, dh_peer, waltplatform_user):
        update_hub_metadata(blocking = self.blocking,
                           requester = context.requester.do_sync,
                                task = context.task,
                             dh_peer = dh_peer,
                           auth_conf = auth_conf,
                   waltplatform_user = waltplatform_user)

