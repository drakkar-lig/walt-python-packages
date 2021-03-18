import sys, os
from time import time
from datetime import datetime
from collections import defaultdict

from walt.server.threads.main.images.image import NodeImage, format_image_fullname
from walt.server.threads.main.network import tftp
from walt.server.threads.main import exports
from walt.server.threads.main.images.setup import setup
from walt.common.tools import failsafe_makedirs


# About terminology: See comment about it in image.py.

# Notes about mount grace time:
# When the last node using an image is associated to another image,
# this previous image should be unmounted since it is not used anymore.
# however, if this image defines /bin/walt-reboot, rebooting the node
# involves code from this previous image. In order to allow this pattern,
# we implement a grace period before an unused image is really unmounted.
# 1st call to update_image_mounts() defines a deadline; next calls verify
# if this deadline is reached and if true unmount the image.
# If ever an image is reused before the grace time is expired, then the
# deadline is removed.

MOUNT_GRACE_TIME = 60
MOUNT_GRACE_TIME_MARGIN = 10

MSG_IMAGE_IS_USED_BUT_NOT_FOUND=\
    "WARNING: image %s is not found. Cannot attach it to related nodes.\n"
CONFIG_ITEM_DEFAULT_IMAGE='default_image'
MSG_WOULD_OVERWRITE_IMAGE="""\
An image has the same name in your working set.
This operation would overwrite it%s.
"""
MSG_WOULD_OVERWRITE_IMAGE_REBOOTED_NODES='\
 (and reboot %d node(s))'

MSG_RESTORING_PULL = """\
NOTE: Daemon was interrupted while pulling image %s. Restoring this background process."""

MSG_PULLING_FROM_DOCKER = """\
NOTE: Pulling image %s from docker daemon to podman storage (migration v4->v5)."""

MSG_IMAGE_READY_BUT_MISSING = """\
Image %s is marked ready in db, but walt does not have it in its own repo! Aborting."""

MSG_WOULD_REBOOT_NODES = """\
This operation would reboot %d node(s) currently using the image.
"""

IMAGE_MOUNT_PATH='/var/lib/walt/images/%s/fs'

def get_mount_path(image_id):
    return IMAGE_MOUNT_PATH % image_id

class NodeImageStore(object):
    def __init__(self, server):
        self.server = server
        self.docker = server.docker
        self.db = server.db
        self.images = {}
        self.mounts = set()
        self.deadlines = {}
    def refresh(self, startup = False):
        db_images = { db_img.fullname: db_img.ready \
                        for db_img in self.db.select('images') }
        # gather local images
        podman_images = set(self.docker.local.get_images())
        if startup:
            docker_images = set(self.docker.daemon.images())
        # import new images from podman into the database
        for fullname in podman_images:
            if fullname not in db_images:
                self.db.insert('images', fullname=fullname, ready=True)
                db_images[fullname] = True
        # update images listed in db and add missing ones
        for db_fullname in db_images:
            db_ready = db_images[db_fullname]
            if db_fullname not in self.images:
                if db_fullname in podman_images:
                    # add missing image in this store
                    self.images[db_fullname] = NodeImage(self, db_fullname)
                else:
                    # if the daemon is starting, check if we should pull images
                    # from docker daemon to podman storage (migration v4->v5)
                    if startup:
                        if db_fullname in docker_images:
                            print(MSG_PULLING_FROM_DOCKER % db_fullname)
                            self.docker.daemon.pull(db_fullname)
                            self.images[db_fullname] = NodeImage(self, db_fullname)
                        else:
                            print(MSG_RESTORING_PULL % db_fullname)
                            self.images[db_fullname] = NodeImage(self, db_fullname)
                            self.server.nodes.restore_interrupted_registration(db_fullname)
                    else:
                        assert (db_ready == False), \
                            MSG_IMAGE_READY_BUT_MISSING % db_fullname
                        # image is not ready yet (probably being pulled)
                        self.images[db_fullname] = NodeImage(self, db_fullname)
        # remove deleted images
        for fullname in list(self.images.keys()):
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
    def __getitem__(self, image_fullname):
        if image_fullname not in self.images:
            # image was probably downloaded using docker commands,
            # walt does not know it yet
            self.refresh()
        return self.images[image_fullname]
    def __iter__(self):
        return iter(self.images.keys())
    def __len__(self):
        return len(self.images)
    def keys(self):
        return self.images.keys()
    def iteritems(self):
        return self.images.items()
    def itervalues(self):
        return self.images.values()
    def values(self):
        return self.images.values()
    # look for an image belonging to the requester.
    # The 'expected' parameter allows to specify if we expect a matching
    # result (expected = True), no matching result (expected = False),
    # or if both options are ok (expected = None).
    # If expected is True or False and the result does not match expectation,
    # an error message will be printed.
    def get_user_image_from_name(self, requester, image_name, expected = True, ready_only = True):
        found = None
        if '/' in image_name:
            fullname = image_name
        else:
            username = requester.get_username()
            if not username:
                return None    # client already disconnected, give up
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
    def get_user_unused_image_from_name(self, requester, image_name):
        image = self.get_user_image_from_name(requester, image_name)
        if image:   # otherwise issue is already reported
            if image.in_use:
                requester.stderr.write('Sorry, cannot proceed because the image is in use.\n')
                return None
        return image
    def update_image_mounts(self, requester = None):
        curr_time = time()
        new_mounts = set()
        # ensure all needed images are mounted
        for fullname in self.get_images_in_use():
            if fullname in self.images:
                img = self.images[fullname]
                if img.ready:
                    if not img.mounted:
                        self.mount(img.image_id, img.fullname)
                    new_mounts.add(img.image_id)
                    # if image was re-mounted while it was waiting grace time
                    # expiry, remove the deadline
                    if img.image_id in self.deadlines:
                        del self.deadlines[img.image_id]
            else:
                sys.stderr.write(MSG_IMAGE_IS_USED_BUT_NOT_FOUND % fullname)
        # check which images should be unmounted
        # (see notes about the grace time at the top of this file)
        to_be_unmounted = set()
        all_mounts = new_mounts
        for image_id in self.mounts - new_mounts:
            deadline = self.deadlines.get(image_id)
            if deadline is None:
                # first time check: set the deadline value
                self.deadlines[image_id] = curr_time + MOUNT_GRACE_TIME
                all_mounts.add(image_id)
            else:
                # next checks: really umount after the deadline expired
                if deadline < curr_time:
                    to_be_unmounted.add(image_id)
                    del self.deadlines[image_id]
                else:
                    all_mounts.add(image_id) # deadline not reached yet
        # recheck after the next deadline if any
        if len(self.deadlines) > 0:
            next_recheck_ts = min(self.deadlines.values()) + \
                              MOUNT_GRACE_TIME_MARGIN
            self.server.ev_loop.plan_event(
                ts = next_recheck_ts,
                callback = self.update_image_mounts
            )
        # update nfs and tftp configuration
        images_info = set((image_id, self.get_mount_path(image_id)) \
                         for image_id in all_mounts)
        nodes_found = self.db.select("nodes")
        exports.update_exported_filesystems(images_info, nodes_found)
        tftp.update(self.db, self)
        # unmount images found above
        # note: this must be done after nfs unmount (otherwise directories would
        # be locked by the NFS export)
        for image_id in to_be_unmounted:
            self.unmount(image_id)
    def cleanup(self):
        if len(self.mounts) > 0:
            # release nfs mounts
            exports.update_exported_filesystems([], [])
            # unmount images
            for image_id in self.mounts.copy():
                self.unmount(image_id)
    def get_images_in_use(self):
        res = set([ item.image for item in \
            self.db.execute("""
                SELECT DISTINCT image FROM nodes""").fetchall()])
        return res
    def get_default_image_fullname(self, node_model):
        return 'waltplatform/%s-default:latest' % node_model
    def image_is_used(self, fullname):
        return self.num_nodes_using_image(fullname) > 0
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
    def warn_if_would_reboot_nodes(self, requester, image_name):
        if '/' in image_name:
            image_fullname = image_name
        else:
            image_fullname = format_image_fullname(requester.get_username(), image_name)
        num_nodes = self.num_nodes_using_image(image_fullname)
        if num_nodes == 0:
            return False    # no node would reboot
        requester.stderr.write(MSG_WOULD_REBOOT_NODES % num_nodes)
        return True     # yes it would reboot some nodes
    def image_is_mounted(self, image_id):
        return image_id in self.mounts
    def get_mount_path(self, image_id):
        if image_id in self.mounts:
            return get_mount_path(image_id)
        else:
            return None
    def mount(self, image_id, fullname = None):
        if image_id in self.mounts:
            return  # already mounted
        self.mounts.add(image_id)
        desc = fullname if fullname else image_id
        print('Mounting %s...' % desc)
        mount_path = get_mount_path(image_id)
        failsafe_makedirs(mount_path)
        self.docker.local.image_mount(image_id, mount_path)
        setup(mount_path)
        print('Mounting %s... done' % desc)
    def unmount(self, image_id, fullname = None):
        if image_id not in self.mounts:
            return  # not mounted
        self.mounts.remove(image_id)
        desc = fullname if fullname else image_id
        print('Un-mounting %s...' % desc, end=' ')
        mount_path = get_mount_path(image_id)
        self.docker.local.image_umount(image_id, mount_path)
        os.rmdir(mount_path)
        print('done')
    def __del__(self):
        self.cleanup()
