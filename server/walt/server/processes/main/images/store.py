from __future__ import annotations

import os
import typing

import sys
from time import time

from walt.common.tools import failsafe_makedirs
from walt.server.processes.main import exports
from walt.server.processes.main.images.image import NodeImage, format_image_fullname
from walt.server.processes.main.images.setup import setup
from walt.server.processes.main.network import tftp
from walt.server.processes.main.filesystem import FilesystemsCache

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server

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

FS_CMD_PATTERN = 'podman run -i --rm -w /root --entrypoint /bin/sh %(fs_id)s'

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
    def __init__(self, server: Server):
        self.server = server
        self.repository = server.repository
        self.blocking = server.blocking
        self.db = server.db
        self.images: dict[str, NodeImage] = {}
        self.mounts = set()
        self.deadlines = {}
        self.filesystems = FilesystemsCache(server.ev_loop, FS_CMD_PATTERN)

    def resync_from_db(self):
        "Synchronization function called on daemon startup."
        db_images = { db_img.fullname: db_img.ready \
                        for db_img in self.db.select('images') }
        # gather local images
        podman_images = set(self.repository.get_images())
        docker_images = None  # Loaded on-demand thereafter
        # import new images from podman into the database
        for fullname in podman_images:
            if fullname not in db_images:
                self.db.insert('images', fullname=fullname, ready=True)
                db_images[fullname] = True
        # update images listed in db and add missing ones to this store
        for db_fullname, db_ready in db_images.items():
            if db_fullname not in self.images:
                if db_fullname in podman_images:
                    # add missing image in this store
                    self.images[db_fullname] = NodeImage(self, db_fullname)
                    continue
                if not db_ready:
                    print(MSG_RESTORING_PULL % db_fullname)
                    self.images[db_fullname] = NodeImage(self, db_fullname)
                    self.server.nodes.restore_interrupted_registration(db_fullname)
                    continue
                if db_ready:
                    # image is known and ready in db, but missing in walt (podman) images
                    # check if we should pull images from docker daemon to
                    # podman storage (migration v4->v5)
                    if docker_images is None:  # Loaded on-demand
                        docker_images = set(self.blocking.sync_list_docker_daemon_images())
                    if db_fullname in docker_images:
                        print(MSG_PULLING_FROM_DOCKER % db_fullname)
                        self.blocking.sync_pull_docker_daemon_image(db_fullname)
                        self.images[db_fullname] = NodeImage(self, db_fullname)
                        continue
                    # Ready, but not found anywhere
                    print("Unable to find image %s. Hope it is not used and remove it." % \
                          db_fullname, file=sys.stderr)
                    self.db.delete('images', fullname=db_fullname)
                    self.db.commit()

    def resync_from_repository(self, rescan = False):
        "Resync function podman repo -> this image store"
        db_images = { db_img.fullname: db_img.ready \
                        for db_img in self.db.select('images') }
        # gather local images
        if rescan:
            self.repository.scan()
        podman_images = set(self.repository.get_images())
        # import new images from podman into this store (and into the database)
        for fullname in podman_images:
            if fullname not in db_images:
                self.db.insert('images', fullname=fullname, ready=True)
                self.db.commit()
                db_images[fullname] = True  # for the next loop below
            if fullname not in self.images:
                self.images[fullname] = NodeImage(self, fullname)
        # all images marked ready should be available in this store
        # if not, this means they were deleted from repository,
        # so remove them here too (and in db)
        for fullname in tuple(self.images):
            ready = db_images[fullname]
            if not ready:
                continue
            if fullname not in podman_images:
                self.remove(fullname)

    def get_labels(self):
        return { fullname: image.labels for fullname, image in self.images.items() }

    def register_image(self, image_fullname, is_ready):
        self.db.insert('images', fullname=image_fullname, ready=is_ready)
        self.db.commit()
        self.images[image_fullname] = NodeImage(self, image_fullname)

    # Make sure to rename the image in docker *before* calling this.
    def rename(self, old_fullname, new_fullname):
        self.db.execute('update images set fullname = %(new_fullname)s where fullname = %(old_fullname)s',
                            dict(old_fullname = old_fullname, new_fullname = new_fullname))
        self.db.commit()
        img = self.images[old_fullname]
        img.rename(new_fullname)
        self.images[new_fullname] = img
        del self.images[old_fullname]

    # Make sure to remove the image from docker *before* calling this.
    def remove(self, image_fullname):
        self.db.delete('images', fullname=image_fullname)
        self.db.commit()
        del self.images[image_fullname]

    def __getitem__(self, image_fullname):
        if image_fullname not in self.images:
            # image was probably downloaded using podman commands
            # (e.g. by the blocking process), main process does not know it yet
            self.repository.refresh_cache_for_image(image_fullname)
            self.resync_from_repository()
        return self.images[image_fullname]

    def __iter__(self):
        return iter(self.images.keys())

    def __len__(self):
        return len(self.images)

    def __contains__(self, image_fullname):
        return image_fullname in self.images

    def keys(self):
        return self.images.keys()

    def values(self):
        return self.images.values()

    def get_user_image_from_name(self, requester, image_name,
                                 expected: bool | None = True, ready_only = True):
        """Look for an image belonging to the requester.

        :param expected: specify if we expect a matching result (True), no
        matching result (False), or if both options are ok (expected = None).
        If expected is True or False and the result does not match expectation,
        an error message will be printed.
        """
        found = None
        username = requester.get_username()
        if not username:
            return None    # client already disconnected, give up
        fullname = format_image_fullname(username, image_name)
        for image in self.images.values():
            if image.fullname == fullname:
                found = image
        if fullname not in self.images and self.count_images_of_user(username) == 0:
            # new user, try to make his life easier by cloning
            # default images of node models present on the platform.
            self.clone_default_images(requester)
        found = self.images.get(fullname)
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

    def count_images_of_user(self, username):
        return sum(1 for image in self.images.values() if image.user == username)

    def get_user_unused_image_from_name(self, requester, image_name):
        image = self.get_user_image_from_name(requester, image_name)
        if image:   # otherwise issue is already reported
            if image.in_use():
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
        # release filesystem interpreters
        for image_id in to_be_unmounted:
            if image_id in self.filesystems:
                del self.filesystems[image_id]
        # unmount images found above
        # note: this must be done after nfs unmount (otherwise directories would
        # be locked by the NFS export)
        for image_id in to_be_unmounted:
            self.unmount(image_id)

    def cleanup(self):
        # release filesystem interpreters
        self.filesystems.cleanup()
        if len(self.mounts) > 0:
            # release nfs mounts
            exports.update_exported_filesystems([], [])
            # unmount images
            for image_id in self.mounts.copy():
                self.unmount(image_id)

    def get_images_in_use(self):
        res = set([ item.image for item in \
            self.db.execute("SELECT DISTINCT image FROM nodes") ])
        return res

    def get_default_image_fullname(self, node_model):
        return 'waltplatform/%s-default:latest' % node_model

    def image_is_used(self, fullname):
        return self.num_nodes_using_image(fullname) > 0

    def num_nodes_using_image(self, image_fullname):
        return len(self.db.select("nodes", image=image_fullname))

    def get_image_overwrite_warning(self, image_fullname):
        num_nodes = self.num_nodes_using_image(image_fullname)
        if num_nodes == 0:
            reboot_message = ''
        else:
            reboot_message = MSG_WOULD_OVERWRITE_IMAGE_REBOOTED_NODES % num_nodes
        return MSG_WOULD_OVERWRITE_IMAGE % reboot_message

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

    def get_filesystem(self, image_id):
        return self.filesystems[image_id]

    def mount(self, image_id, fullname = None):
        if image_id in self.mounts:
            return  # already mounted
        self.mounts.add(image_id)
        desc = fullname if fullname else image_id
        print('Mounting %s...' % desc)
        mount_path = get_mount_path(image_id)
        failsafe_makedirs(mount_path)
        self.repository.image_mount(image_id, mount_path)
        setup(mount_path)
        print('Mounting %s... done' % desc)

    def unmount(self, image_id, fullname = None):
        if image_id not in self.mounts:
            return  # not mounted
        self.mounts.remove(image_id)
        desc = fullname if fullname else image_id
        print('Un-mounting %s...' % desc, end=' ')
        mount_path = get_mount_path(image_id)
        self.repository.image_umount(image_id, mount_path)
        os.rmdir(mount_path)
        print('done')

    def __del__(self):
        self.cleanup()

    def clone_default_images(self, requester):
        username = requester.get_username()
        if not username:
            return False     # client already disconnected, give up
        node_models = set(n.model for n in self.db.select('nodes'))
        if len(node_models) == 0:   # no nodes
            return False
        requester.set_busy_label('Cloning default images')
        while len(node_models) > 0:
            model = node_models.pop()
            default_image = self.get_default_image_fullname(model)
            # if default image has a 'preferred-name' tag, clone it with that name
            default_image_labels = self.images[default_image].labels
            image_name = default_image_labels.get('walt.image.preferred-name')
            if image_name is None:
                # no 'preferred-name' tag, reuse name of default image
                image_name = default_image.split('/')[1]
            ws_image = username + '/' + image_name
            self.repository.tag(default_image, ws_image)
            self.register_image(ws_image, True)
            # remove from remaining models all models declared in label "walt.node.models"
            image_models = default_image_labels.get('walt.node.models').split(',')
            node_models -= set(image_models)
        requester.set_default_busy_label()
        return True
