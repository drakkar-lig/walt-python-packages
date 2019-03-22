import sys
from datetime import datetime

from walt.server.threads.main.images.image import NodeImage, format_image_fullname
from walt.server.threads.main.network import nfs


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

MSG_REMOVING_FROM_DB = """\
WARNING: Removing image %s from db because docker does not list it."""

MSG_IMAGE_READY_BUT_MISSING = """\
Image %s is marked ready in db, but docker does not list it! Aborting."""

class NodeImageStore(object):
    def __init__(self, docker, db):
        self.docker = docker
        self.db = db
        self.images = {}
    def refresh(self, startup = False):
        db_images = { db_img.fullname: db_img.ready \
                        for db_img in self.db.select('images') }
        docker_images = {}
        # gather local images
        for image in self.docker.local.get_images():
            # restrict to images with a label 'walt.node.models'
            if image['Labels'] is None:
                continue
            if 'walt.node.models' not in image['Labels']:
                continue
            if image['RepoTags'] is None:   # dangling image
                continue
            for fullname in image['RepoTags']:
                # discard dangling images and tags temporarily added
                # for a 'clone' operation
                if '/' in fullname and 'clone-temp/walt-image:' not in fullname:
                    docker_images[fullname] = image
        # import new images from docker into the database
        for fullname in docker_images:
            if fullname not in db_images:
                self.db.insert('images', fullname=fullname, ready=True)
                db_images[fullname] = True
        # add missing images
        for db_fullname in db_images:
            db_ready = db_images[db_fullname]
            if db_fullname not in self.images:
                if db_fullname in docker_images:
                    created_at = datetime.fromtimestamp(
                            docker_images[db_fullname]['Created'])
                    self.images[db_fullname] = NodeImage(self.db,
                                self.docker, db_fullname, created_at)
                else:
                    # if the daemon is starting, remove images from db not listed
                    # by docker.
                    if startup:
                        print(MSG_REMOVING_FROM_DB % db_fullname)
                        self.db.delete('images', fullname = db_fullname)
                    else:
                        assert (db_ready == False), \
                            MSG_IMAGE_READY_BUT_MISSING % db_fullname
                        # image is not ready yet (probably being pulled)
                        self.images[db_fullname] = NodeImage(self.db,
                                            self.docker, db_fullname)
        # remove deleted images
        for fullname in self.images.keys():
            if fullname not in db_images:
                del self.images[fullname]
    def register_image(self, image_fullname, is_ready):
        self.db.insert('images', fullname=image_fullname, ready=is_ready)
        self.db.commit()
        self.refresh()
    # Make sure to rename the image in docker *before* calling this.
    def rename(self, old_fullname, new_fullname):
        self.db.execute('update images set fullname = %(new_fullname)s where fullname = %(old_fullname)s',
                            dict(old_fullname = old_fullname, new_fullname = new_fullname))
        self.db.commit()
        self.refresh()
    # Make sure to remove the image from docker *before* calling this.
    def remove(self, image_fullname):
        self.db.delete('images', fullname=image_fullname)
        self.db.commit()
        self.refresh()
    def set_image_ready(self, image_fullname):
        self.db.update('images', 'fullname', fullname=image_fullname, ready=True)
        self.db.commit()
    def __getitem__(self, image_fullname):
        if image_fullname not in self.images:
            # image was probably downloaded using docker commands,
            # walt does not know it yet
            self.refresh()
        return self.images[image_fullname]
    def __iter__(self):
        return self.images.iterkeys()
    def __len__(self):
        return len(self.images)
    def keys(self):
        return self.images.keys()
    def iteritems(self):
        return self.images.iteritems()
    def itervalues(self):
        return self.images.itervalues()
    def values(self):
        return self.images.values()
    # look for an image belonging to the requester.
    # The 'expected' parameter allows to specify if we expect a matching
    # result (expected = True), no matching result (expected = False),
    # or if both options are ok (expected = None).
    # If expected is True or False and the result does not match expectation,
    # an error message will be printed.
    def get_user_image_from_name(self, requester, image_name, expected = True, ready_only = True):
        username = requester.get_username()
        if not username:
            return None    # client already disconnected, give up
        found = None
        fullname = format_image_fullname(username, image_name)
        for image in self.images.values():
            if image.fullname == fullname:
                found = image
        if expected == True and found is None:
            requester.stderr.write(
                "Error: No such image '%s'. (tip: walt image show)\n" % image_name)
        if expected == False and found is not None:
            requester.stderr.write(
                "Error: Image '%s' already exists.\n" % image_name)
        if expected == True and found is not None:
            if ready_only and found.ready == False:
                requester.stderr.write(
                    "Error: Image '%s' is not ready.\n" % image_name)
                found = None
        return found
    def get_user_unmounted_image_from_name(self, requester, image_name):
        image = self.get_user_image_from_name(requester, image_name)
        if image:   # otherwise issue is already reported
            if image.mounted:
                requester.stderr.write('Sorry, cannot proceed because the image is mounted.\n')
                return None
        return image
    def update_image_mounts(self, images_in_use = None, requester = None):
        if images_in_use == None:
            images_in_use = self.get_images_in_use()
        images_found = []
        nodes_found = self.db.select("nodes")
        # ensure all needed images are mounted
        for fullname in images_in_use:
            if fullname in self.images:
                img = self.images[fullname]
                if not img.mounted:
                    img.mount(requester = requester)
                images_found.append(img)
            else:
                sys.stderr.write(MSG_IMAGE_IS_USED_BUT_NOT_FOUND % fullname)
        # update nfs configuration
        nfs.update_exported_filesystems(images_found, nodes_found)
        # unmount images that are not needed anymore
        for fullname in self.images:
            if fullname not in images_in_use:
                img = self.images[fullname]
                if img.mounted:
                    img.unmount()
    def cleanup(self):
        # release nfs mounts
        nfs.update_exported_filesystems([], [])
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
    def get_default_image_fullname(self, node_model):
        return 'waltplatform/%s-default:latest' % node_model
    def umount_used_image(self, image):
        images = self.get_images_in_use()
        images.remove(image.fullname)
        self.update_image_mounts(images_in_use = images)
    def num_nodes_using_image(self, image_fullname):
        return len(self.db.select("nodes", image=image_fullname))
    def warn_overwrite_image(self, requester, image_name):
        image_fullname = format_image_fullname(requester.get_username(), image_name)
        num_nodes = self.num_nodes_using_image(image_fullname)
        if num_nodes == 0:
            reboot_message = ''
        else:
            reboot_message = MSG_WOULD_OVERWRITE_IMAGE_REBOOTED_NODES % num_nodes
        requester.stderr.write(MSG_WOULD_OVERWRITE_IMAGE % reboot_message)

