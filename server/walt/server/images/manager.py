import re, sys
from docker import Client
from walt.server.images.image import get_mount_path, NodeImage
from walt.server.images.shell import ModifySession
from walt.server.images.search import search
from walt.server.images.clone import clone
from walt.server.images.show import show
from walt.server.images.store import NodeImageStore
from walt.server.network import nfs
from walt.common.tools import \
        failsafe_makedirs, failsafe_symlink

# About terminology: See comment about it in image.py.

IMAGE_IS_USED_BUT_NOT_FOUND=\
    "WARNING: image %s is not found. Cannot attach it to related nodes.\n"
CONFIG_ITEM_DEFAULT_IMAGE='default_image'

class NodeImageManager(object):
    def __init__(self, db, blocking_manager):
        self.db = db
        self.blocking = blocking_manager
        self.c = Client(base_url='unix://var/run/docker.sock', version='auto')
        self.modify_sessions = set()
        self.images = NodeImageStore(self.c)
        self.images.refresh()
    def search(self, requester, q, keyword):
        search(q, self.blocking, self.c, requester, keyword)
    def clone(self, requester, q, clonable_link):
        clone(q, self.blocking, self.c, requester, clonable_link, self.images)
    def show(self, username):
        return show(self.images, username)
    def update_image_mounts(self, images_in_use = None):
        if images_in_use == None:
            images_in_use = self.get_images_in_use()
        images_found = []
        # ensure all needed images are mounted
        for fullname in images_in_use:
            if fullname in self.images:
                img = self.images[fullname]
                if not img.mounted:
                    img.mount()
                images_found.append(img)
            else:
                sys.stderr.write(IMAGE_IS_USED_BUT_NOT_FOUND % fullname)
        # update default image link
        self.update_default_link()
        # update nfs configuration
        nfs.update_exported_filesystems(images_found)
        # unmount images that are not needed anymore
        for fullname in self.images:
            if fullname not in images_in_use:
                img = self.images[fullname]
                if img.mounted:
                    img.unmount()
    def cleanup(self):
        # give up modify sessions
        for session in self.modify_sessions.copy():
            self.cleanup_modify_session(session)
        # release nfs mounts
        nfs.update_exported_filesystems([])
        # unmount images
        for fullname in self.images:
            img = self.images[fullname]
            if img.mounted:
                img.unmount()
    def get_images_in_use(self):
        res = set([ item.image for item in \
            self.db.execute("""
                SELECT DISTINCT image FROM nodes""").fetchall()])
        res.add(self.get_default_image())
        return res
    def get_default_image(self):
        if len(self.images) > 0:
            default_if_not_specified = self.images.keys()[0]
        else:
            default_if_not_specified = None
        return self.db.get_config(
                    CONFIG_ITEM_DEFAULT_IMAGE,
                    default_if_not_specified)
    def update_default_link(self):
        default_image = self.get_default_image()
        default_mount_path = get_mount_path(default_image)
        default_simlink = get_mount_path('default')
        failsafe_makedirs(default_mount_path)
        failsafe_symlink(default_mount_path, default_simlink)
    def get_image_from_tag(self, image_tag, requester = None):
        for image in self.images.values():
            if image.tag == image_tag:
                return image
        if requester:
            requester.stderr.write(
                "No such image '%s'. (tip: walt image show)\n" % image_tag)
        return None
    def has_image(self, requester, image_tag):
        return self.get_image_from_tag(image_tag, requester) != None
    def set_image(self, requester, node_mac, image_tag):
        image = self.get_image_from_tag(image_tag, requester)
        if image:
            self.db.update('nodes', 'mac',
                    mac=node_mac,
                    image=image.fullname)
            self.update_image_mounts()
            self.db.commit()
    def set_default(self, requester, image_tag):
        image = self.get_image_from_tag(image_tag, requester)
        if image:
            self.db.set_config(
                    CONFIG_ITEM_DEFAULT_IMAGE,
                    image.fullname)
            self.update_image_mounts()
            self.db.commit()
    def create_modify_session(self, requester, image_tag):
        image = self.get_image_from_tag(image_tag, requester)
        if not image:
            requester.stderr.write('No such image.\n')
            return None
        else:
            return ModifySession(requester, image.fullname, self)
    def get_default_new_image_tag(self, requester, old_image_tag):
        image = self.get_image_from_tag(old_image_tag)
        if image.user == requester.username:
            # we can override the image, since we own it
            # => propose the same name
            return old_image_tag
        else:
            # we cannot override the image, since we do not own it
            # => propose another name
            new_tag = old_image_tag
            while self.get_image_from_tag(new_tag):
                new_tag += '_new'
            return new_tag
    def validate_new_image_tag(self, requester, old_image_tag, new_image_tag):
        existing_image = self.get_image_from_tag(new_image_tag)
        if old_image_tag == new_image_tag:
            # same name for the modified image.
            if existing_image.user != requester.username:
                requester.stderr.write(MSG_BAD_NAME_SAME_AND_NOT_OWNER)
                return ModifySession.NAME_NOT_OK
            # since the user owns the image, he is allowed to overwrite it with the modified one.
            # however, we will let the user confirm this.
            num_nodes = len(self.db.select("nodes", image=existing_image.fullname))
            reboot_message = '' if num_nodes == 0 else ' (and reboot %d node(s))' % num_nodes
            requester.stderr.write('This would overwrite the existing image%s.\n' % reboot_message)
            return ModifySession.NAME_NEEDS_CONFIRM
        else:
            if existing_image:
                requester.stderr.write('Bad name: Image already exists.\n')
                return ModifySession.NAME_NOT_OK
        if not re.match('^[a-zA-Z0-9\-_]+$', new_image_tag):
            requester.stderr.write(\
                'Bad name: Only alnum, dash(-) and underscore(_) characters are allowed.\n')
            return ModifySession.NAME_NOT_OK
        return ModifySession.NAME_OK
    def register_modify_session(self, session):
        self.modify_sessions.add(session)
    def cleanup_modify_session(self, session):
        cname = session.container_name
        # kill/remove the container if it ever existed
        try:
            self.c.kill(container=cname)
        except:
            pass
        try:
            self.c.wait(container=cname)
        except:
            pass
        try:
            self.c.remove_container(container=cname)
        except:
            pass
        self.modify_sessions.remove(session)

    def umount_used_image(self, image):
        images = self.get_images_in_use()
        images.remove(image.fullname)
        self.update_image_mounts(images)

    def finalize_modify(self, session):
        requester = session.requester
        old_image_tag = session.image_tag
        new_image_tag = session.new_image_tag
        container_name = session.container_name
        if new_image_tag:
            image_name = '%s/walt-node' % requester.username
            self.c.commit(
                    container=container_name,
                    repository=image_name,
                    tag=new_image_tag,
                    message='Image modified using walt image shell')
            if old_image_tag == new_image_tag:
                # same name, we are modifying the image
                image = self.get_image_from_tag(new_image_tag)
                # if image is mounted, umount/mount it in order to make
                # the nodes reboot with the new version
                if image.mounted:
                    # umount
                    self.umount_used_image(image)
                    # re-mount
                    self.update_image_mounts()
                # done.
                requester.stdout.write('Image %s updated.\n' % new_image_tag)
            else:
                # we are saving changes to a new image, leaving the initial one
                # unchanged
                fullname = '%s:%s' % (image_name, new_image_tag)
                self.images[fullname] = NodeImage(self.c, fullname, NodeImage.LOCAL)
                requester.stdout.write('New image %s saved.\n' % new_image_tag)
        self.cleanup_modify_session(session)

    def get_local_unmounted_image_from_tag(self, image_tag, requester):
        image = self.get_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            if image.state != NodeImage.LOCAL:
                requester.stderr.write('Sorry, this operation is allowed on local images only.\n')
                return None
            if image.mounted:
                requester.stderr.write('Sorry, cannot proceed because the image is mounted.\n')
                return None
        return image

    def remove(self, requester, image_tag):
        image = self.get_local_unmounted_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            name = image.fullname
            del self.images[name]
            self.c.remove_image(
                    image=name, force=True)

    def do_rename(self, image, new_user, new_tag):
        old_fullname = image.fullname
        new_name = "%s/walt-node" % new_user
        new_fullname = "%s:%s" % (new_name, new_tag)
        # update image internal attributes
        image.rename(new_fullname)
        # rename in this repo
        self.images[new_fullname] = image
        del self.images[old_fullname]
        # rename the docker image
        self.c.tag(image=old_fullname, repository=new_name, tag=new_tag)
        self.c.remove_image(image=old_fullname, force=True)

    def rename(self, requester, image_tag, new_tag):
        image = self.get_local_unmounted_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            if self.get_image_from_tag(new_tag):
                requester.stderr.write('Bad name: Image already exists.\n')
                return
            self.do_rename(image, image.user, new_tag)

    def get_owner(self, requester, image_tag):
        image = self.get_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            return image.user

    def fix_owner(self, requester, image_tag):
        image = self.get_local_unmounted_image_from_tag(image_tag, requester)
        if image:   # otherwise issue is already reported
            self.do_rename(image, requester.username, image_tag)

