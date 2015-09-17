import sys
from walt.server.images.image import NodeImage
from walt.server.network import nfs
from walt.common.tools import \
        failsafe_makedirs, failsafe_symlink
from walt.server.images.image import get_mount_path
# About terminology: See comment about it in image.py.

MSG_IMAGE_IS_USED_BUT_NOT_FOUND=\
    "WARNING: image %s is not found. Cannot attach it to related nodes.\n"
CONFIG_ITEM_DEFAULT_IMAGE='default_image'
MSG_WOULD_OVERWRITE_IMAGE="""\
An image has the same name in your working set.
This operation would overwrite it%s.
"""
MSG_WOULD_OVERWRITE_IMAGE_REBOOTED_NODES='\
 (and reboot %d node(s))'

class NodeImageStore(object):
    def __init__(self, docker, db):
        self.docker = docker
        self.db = db
        self.images = {}
    def refresh(self):
        local_images = self.docker.get_local_images()
        # add missing images
        for fullname in local_images:
            if '/walt-node' in fullname and fullname not in self.images:
                self.images[fullname] = NodeImage(self.docker, fullname)
        # remove deleted images
        for fullname in self.images.keys():
            if fullname not in local_images:
                del self.images[fullname]
    def __getitem__(self, image_fullname):
        return self.images[image_fullname]
    def __iter__(self):
        return self.images.iterkeys()
    def __len__(self):
        return len(self.images)
    def keys(self):
        return self.images.keys()
    def iteritems(self):
        return self.images.iteritems()
    def values(self):
        return self.images.values()
    # look for an image belonging to the requester.
    # The 'expected' parameter allows to specify if we expect a matching
    # result (expected = True), no matching result (expected = False),
    # or if both options are ok (expected = None).
    # If expected is True or False and the result does not match expectation,
    # an error message will be printed.
    def get_user_image_from_tag(self, requester, image_tag, expected = True):
        found = None
        for image in self.images.values():
            if image.tag == image_tag and image.user == requester.username:
                found = image
        if expected == True and found is None:
            requester.stderr.write(
                "Error: No such image '%s'. (tip: walt image show)\n" % image_tag)
        if expected == False and found is not None:
            requester.stderr.write(
                "Error: Image '%s' already exists.\n" % image_tag)
        return found
    def get_user_unmounted_image_from_tag(self, requester, image_tag):
        image = self.get_user_image_from_tag(requester, image_tag)
        if image:   # otherwise issue is already reported
            if image.mounted:
                requester.stderr.write('Sorry, cannot proceed because the image is mounted.\n')
                return None
        return image
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
                sys.stderr.write(MSG_IMAGE_IS_USED_BUT_NOT_FOUND % fullname)
        # update nfs configuration
        nfs.update_exported_filesystems(images_found)
        # unmount images that are not needed anymore
        for fullname in self.images:
            if fullname not in images_in_use:
                img = self.images[fullname]
                if img.mounted:
                    img.unmount()
    def cleanup(self):
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
        return res
    def get_default_image(self, node_type):
        return 'waltplatform/walt-node:%s-default' % node_type
    def umount_used_image(self, image):
        images = self.get_images_in_use()
        images.remove(image.fullname)
        self.update_image_mounts(images)
    def warn_overwrite_image(self, requester, image_fullname):
        num_nodes = len(self.db.select("nodes", image=image_fullname))
        if num_nodes == 0:
            reboot_message = ''
        else:
            reboot_message = MSG_WOULD_OVERWRITE_IMAGE_REBOOTED_NODES % num_nodes
        requester.stderr.write(MSG_WOULD_OVERWRITE_IMAGE % reboot_message)

