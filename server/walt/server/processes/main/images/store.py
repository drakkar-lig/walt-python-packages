from __future__ import annotations

import os
import sys
import typing
from time import time

from walt.common.tools import failsafe_makedirs, format_image_fullname
from walt.server.processes.main.exports import FilesystemsExporter
from walt.server.processes.main.filesystem import FilesystemsCache
from walt.server.processes.main.images.image import NodeImage
from walt.server.processes.main.images.setup import setup
from walt.server.processes.main.network import tftp
from walt.server.processes.main.workflow import Workflow

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server

# About terminology: See comment about it in image.py.

# Notes about mount grace time:
# When the last node using an image is associated to another image,
# this previous image should be unmounted since it is not used anymore.
# however, if this image defines /bin/walt-reboot, rebooting the node
# involves code from this previous image. In order to allow this pattern,
# we implement a grace period before an unused image is really unmounted.
# 1st call to wf_update_image_mounts() defines a deadline; next calls verify
# if this deadline is reached and if true unmount the image.
# If ever an image is reused before the grace time is expired, then the
# deadline is removed.

FS_CMD_PATTERN = "podman run -i --rm -w /root --entrypoint /bin/sh %(fs_id)s"

MOUNT_GRACE_TIME = 60
MOUNT_GRACE_TIME_MARGIN = 10

MSG_IMAGE_IS_USED_BUT_NOT_FOUND = (
    "WARNING: image %s is not found. Cannot attach it to related nodes.\n"
)
CONFIG_ITEM_DEFAULT_IMAGE = "default_image"
MSG_WOULD_OVERWRITE_IMAGE = """\
An image has the same name in your working set.
This operation would overwrite it%s.
"""
MSG_WOULD_OVERWRITE_IMAGE_REBOOTED_NODES = " (and reboot %d node(s))"

MSG_PULLING_FROM_DOCKER = """\
NOTE: Pulling image %s from docker daemon to podman storage (migration v4->v5)."""

MSG_WOULD_REBOOT_NODES = """\
This operation would reboot %d node(s) currently using the image.
"""

IMAGE_MOUNT_PATH = "/var/lib/walt/images/%s/fs"


def get_mount_path(image_id):
    return IMAGE_MOUNT_PATH % image_id


class NodeImageStore(object):
    def __init__(self, server: Server):
        self.server = server
        self.registry = server.registry
        self.blocking = server.blocking
        self.db = server.db
        self.images: dict[str, NodeImage] = {}
        self.mounts = set()
        self.deadlines = {}
        self.filesystems = FilesystemsCache(server.ev_loop, FS_CMD_PATTERN)
        self.exports = FilesystemsExporter(server.ev_loop)
        self._update_wf = None
        self._planned_update_wf = None

    def resync_from_db(self):
        "Synchronization function called on daemon startup."
        db_images = set(db_img.fullname for db_img in self.db.select("images"))
        # gather local images
        podman_images = set(self.registry.get_images())
        docker_images = None  # Loaded on-demand thereafter
        # import new images from podman into the database
        for fullname in podman_images:
            if fullname not in db_images:
                self.db.insert("images", fullname=fullname)
                db_images.add(fullname)
        # update images listed in db and add missing ones to this store
        for db_fullname in db_images:
            if db_fullname not in self.images:
                if db_fullname in podman_images:
                    # add missing image in this store
                    self.images[db_fullname] = NodeImage(self, db_fullname)
                    continue
                else:
                    # image is known and found in db, but missing in walt (podman)
                    # images check if we should pull images from docker daemon to podman
                    # storage (migration v4->v5)
                    if docker_images is None:  # Loaded on-demand
                        docker_images = set(
                            self.blocking.sync_list_docker_daemon_images()
                        )
                    if db_fullname in docker_images:
                        print(MSG_PULLING_FROM_DOCKER % db_fullname)
                        self.blocking.sync_pull_docker_daemon_image(db_fullname)
                        self.images[db_fullname] = NodeImage(self, db_fullname)
                        continue
                    # Ready, but not found anywhere
                    print(
                        "Unable to find image %s. Hope it is not used and remove it."
                        % db_fullname,
                        file=sys.stderr,
                    )
                    self.db.delete("images", fullname=db_fullname)
                    self.db.commit()

    def resync_from_registry(self, rescan=False):
        "Resync function podman repo -> this image store"
        db_images = set(db_img.fullname for db_img in self.db.select("images"))
        # gather local images
        if rescan:
            self.registry.scan()
        podman_images = set(self.registry.get_images())
        # import new images from podman into this store (and into the database)
        for fullname in podman_images:
            if fullname not in db_images:
                self.db.insert("images", fullname=fullname)
                self.db.commit()
                db_images.add(fullname)  # for the next loop below
            if fullname not in self.images:
                self.images[fullname] = NodeImage(self, fullname)
        # all images should be available in this store
        # if not, this means they were deleted from registry,
        # so remove them here too (and in db)
        for fullname in tuple(self.images):
            if fullname not in podman_images:
                self.remove(fullname)

    def get_labels(self):
        return {fullname: image.labels for fullname, image in self.images.items()}

    def register_image(self, image_fullname):
        self.db.insert("images", fullname=image_fullname)
        self.db.commit()
        self.images[image_fullname] = NodeImage(self, image_fullname)

    # Make sure to rename the image in docker *before* calling this.
    def rename(self, old_fullname, new_fullname):
        self.db.execute(
            (
                "update images set fullname = %(new_fullname)s"
                " where fullname = %(old_fullname)s"
            ),
            dict(old_fullname=old_fullname, new_fullname=new_fullname),
        )
        self.db.commit()
        img = self.images[old_fullname]
        img.rename(new_fullname)
        self.images[new_fullname] = img
        del self.images[old_fullname]

    # Make sure to remove the image from docker *before* calling this.
    def remove(self, image_fullname):
        self.db.delete("images", fullname=image_fullname)
        self.db.commit()
        del self.images[image_fullname]

    def __getitem__(self, image_fullname):
        if image_fullname not in self.images:
            # image was probably downloaded using podman commands
            # (e.g. by the blocking process), main process does not know it yet
            self.registry.refresh_cache_for_image(image_fullname)
            self.resync_from_registry()
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

    def get_user_image_from_name(
        self, requester, image_name, expected: bool | None = True
    ):
        """Look for an image belonging to the requester.

        :param expected: specify if we expect a matching result (True), no
        matching result (False), or if both options are ok (expected = None).
        If expected is True or False and the result does not match expectation,
        an error message will be printed.
        """
        found = None
        username = requester.get_username()
        if not username:
            return None  # client already disconnected, give up
        fullname = format_image_fullname(username, image_name)
        for image in self.images.values():
            if image.fullname == fullname:
                found = image
        if fullname not in self.images and self.count_images_of_user(username) == 0:
            # new user, try to make his life easier by cloning
            # default images of node models present on the platform.
            self.get_clones_of_default_images(requester, "all-nodes")
        found = self.images.get(fullname)
        if expected is True and found is None:
            requester.stderr.write(
                "Error: No such image '%s'. (tip: walt image show)\n" % image_name
            )
        if expected is False and found is not None:
            requester.stderr.write("Error: Image '%s' already exists.\n" % image_name)
        return found

    def count_images_of_user(self, username):
        return sum(1 for image in self.images.values() if image.user == username)

    def get_user_unused_image_from_name(self, requester, image_name):
        image = self.get_user_image_from_name(requester, image_name)
        if image:  # otherwise issue is already reported
            if image.in_use():
                requester.stderr.write(
                    "Sorry, cannot proceed because the image is in use.\n"
                )
                return None
        return image

    def trigger_update_image_mounts(self):
        wf = Workflow([self.wf_update_image_mounts])
        wf.run()

    def _wf_after_plan_next_update_wf(self, wf, **env):
        self._planned_update_wf = None
        self._plan_next_update_wf()

    def _plan_next_update_wf(self):
        if self._planned_update_wf is None and len(self.deadlines) > 0:
            self._planned_update_wf = Workflow(
                [self.wf_update_image_mounts, self._wf_after_plan_next_update_wf]
            )
            next_time = min(self.deadlines.values()) + MOUNT_GRACE_TIME_MARGIN
            self.server.ev_loop.plan_event(
                ts=next_time, callback=self._planned_update_wf.next
            )

    def wf_update_image_mounts(self, wf, **env):
        # if there is not already an update workflow in progress, create it
        if self._update_wf is None:
            self._update_wf = Workflow([self._wf_update_image_mounts])
            self._update_wf.run()
        # if no change was detected, self._update_wf.run() may be already completed
        # and the value of self._update_wf may have been set back to None.
        if self._update_wf is None:
            wf.next()
        else:
            # wait for the update workflow to be completed
            wf.wait_for_other_workflow(self._update_wf)

    def _wf_update_image_mounts(self, update_wf, **env):
        new_mounts = set()
        to_be_unmounted = set()
        changes = False
        # ensure all needed images are mounted
        for fullname in self.get_images_in_use():
            if fullname in self.images:
                img = self.images[fullname]
                if not img.mounted:
                    changes = True
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
        curr_time = time()
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
                    changes = True
                    to_be_unmounted.add(image_id)
                else:
                    all_mounts.add(image_id)  # deadline not reached yet
        if changes:
            # retrieve info for next steps
            images_info = set(
                (image_id, self.get_mount_path(image_id)) for image_id in all_mounts
            )
            nodes = self.db.select("nodes")
            # release filesystem interpreters before unmounting images
            for image_id in to_be_unmounted:
                if image_id in self.filesystems:
                    del self.filesystems[image_id]
            # next steps:
            # 1. nfs mount / unmount
            # 2. unmount images
            # 3. recurse in case something changed during the run
            # note: step 1 is before step 2 otherwise directories would be locked by
            # the NFS export
            update_wf.insert_steps(
                [
                    self.exports.wf_update_exported_filesystems,
                    self._wf_unmount_images,
                    self._wf_update_image_mounts,
                ]
            )
            update_wf.update_env(
                to_be_unmounted=to_be_unmounted, images_info=images_info, nodes=nodes
            )
        else:
            # finalize this update
            # - update tftp symlinks
            tftp.update(self.db, self)
            # - notify concurrent code that this update workflow is completed
            self._update_wf = None
            # - automatically restart after the next unmount deadline if any
            self._plan_next_update_wf()
        update_wf.next()

    def _wf_unmount_images(self, update_wf, to_be_unmounted, **env):
        for image_id in to_be_unmounted:
            self.unmount(image_id)
            self.deadlines.pop(image_id, None)
        update_wf.next()

    def cleanup(self):
        # release filesystem interpreters
        self.filesystems.cleanup()
        if len(self.mounts) > 0:
            # release nfs mounts and unmount images
            wf = Workflow(
                [self.exports.wf_update_exported_filesystems], images_info=[], nodes=[]
            )
            wf.run()
            # Since we are cleaning up, we cannot use a callback
            # because the event loop will be stopped.
            # So we just let the unmount procedure actively wait
            # for the nfsd service to release the mounted images.
            for image_id in self.mounts.copy():
                self.unmount(image_id)

    def get_images_in_use(self):
        res = set(
            [item.image for item in self.db.execute("SELECT DISTINCT image FROM nodes")]
        )
        return res

    def get_default_image_fullname(self, node_model):
        return "waltplatform/%s-default:latest" % node_model

    def image_is_used(self, fullname):
        return self.num_nodes_using_image(fullname) > 0

    def num_nodes_using_image(self, image_fullname):
        return len(self.db.select("nodes", image=image_fullname))

    def get_image_overwrite_warning(self, image_fullname):
        num_nodes = self.num_nodes_using_image(image_fullname)
        if num_nodes == 0:
            reboot_message = ""
        else:
            reboot_message = MSG_WOULD_OVERWRITE_IMAGE_REBOOTED_NODES % num_nodes
        return MSG_WOULD_OVERWRITE_IMAGE % reboot_message

    def warn_if_would_reboot_nodes(self, requester, image_name):
        if "/" in image_name:
            image_fullname = image_name
        else:
            image_fullname = format_image_fullname(requester.get_username(), image_name)
        num_nodes = self.num_nodes_using_image(image_fullname)
        if num_nodes == 0:
            return False  # no node would reboot
        requester.stderr.write(MSG_WOULD_REBOOT_NODES % num_nodes)
        return True  # yes it would reboot some nodes

    def image_is_mounted(self, image_id):
        return image_id in self.mounts

    def get_mount_path(self, image_id):
        if image_id in self.mounts:
            return get_mount_path(image_id)
        else:
            return None

    def get_filesystem(self, image_id):
        return self.filesystems[image_id]

    def mount(self, image_id, fullname=None):
        if image_id in self.mounts:
            return  # already mounted
        self.mounts.add(image_id)
        desc = fullname if fullname else image_id
        print("Mounting %s..." % desc)
        mount_path = get_mount_path(image_id)
        failsafe_makedirs(mount_path)
        self.registry.image_mount(image_id, mount_path)
        setup(mount_path)
        print("Mounting %s... done" % desc)

    def unmount(self, image_id, fullname=None):
        if image_id not in self.mounts:
            return  # not mounted
        self.mounts.remove(image_id)
        desc = fullname if fullname else image_id
        print("Un-mounting %s..." % desc, end=" ")
        mount_path = get_mount_path(image_id)
        self.registry.image_umount(image_id, mount_path)
        os.rmdir(mount_path)
        print("done")

    def __del__(self):
        self.cleanup()

    def get_clones_of_default_images(self, requester, node_set):
        # returns a tuple of 3 values:
        # 1: whether the request was valid
        # 2: whether some new images have been cloned by this procedure
        # 3: a dictionary indicating the defaut image name for each input node name
        username = requester.get_username()
        if not username:
            return False, False, {}  # client already disconnected, give up
        nodes = self.server.nodes.parse_node_set(requester, node_set)
        if nodes is None:  # issue already reported
            return False, False, {}
        real_update = False
        image_per_node_name = {}
        while len(nodes) > 0:
            model = nodes[0].model
            default_image = self.get_default_image_fullname(model)
            # if default image has a 'preferred-name' tag, clone it with that name
            image_labels = self.images[default_image].labels
            image_name = image_labels.get("walt.image.preferred-name")
            if image_name is None:
                # no 'preferred-name' tag, reuse name of default image
                image_name = default_image.split("/")[1]
            image_node_models = self.images[default_image].node_models
            image_node_models_desc = self.images[default_image].node_models_desc
            ws_image = username + "/" + image_name
            if ws_image not in self.images:
                if real_update is False:
                    real_update = True
                    requester.set_busy_label("Cloning default images")
                self.registry.tag(default_image, ws_image)
                self.register_image(ws_image)
                requester.stdout.write(
                    f"Cloned {image_name}, a defaut image for"
                    f" {image_node_models_desc}.\n"
                )
            # remove from remaining nodes those with a model declared in label
            # "walt.node.models"
            remaining_nodes = []
            for node in nodes:
                if node.model in image_node_models:
                    image_per_node_name[node.name] = image_name
                else:
                    remaining_nodes.append(node)
            nodes = remaining_nodes
        if real_update:
            requester.set_default_busy_label()
        return True, real_update, image_per_node_name
