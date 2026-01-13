from __future__ import annotations

import functools
import sys
import typing

from walt.common.tools import format_image_fullname
from walt.server.processes.main.filesystem import FilesystemsCache
from walt.server.processes.main.images.image import NodeImage
from walt.server.processes.main.images.tools import handle_client_registry_conf_issues

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server

# About terminology: See comment about it in image.py.

FS_CMD_PATTERN = "walt-image-fs-helper %(fs_id)s"

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


class NodeImageStore(object):
    def __init__(self, server: Server):
        self.server = server
        self.registry = server.registry
        self.blocking = server.blocking
        self.db = server.db
        self.images: dict[str, NodeImage] = {}
        self.filesystems = FilesystemsCache(server.ev_loop, FS_CMD_PATTERN)
        self.exports = server.exports

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

    def update_default_images(self, requester, task_cb):
        # we ignore the final reboot status of nodes
        def final_task_cb(status=None):
            task_cb(None)
        update_info = {}
        for fullname, image in self.images.items():
            if (    fullname.startswith('waltplatform/') and \
                    fullname.endswith('-default:latest')
            ):
                update_info[fullname] = image.created_ts
        if len(update_info) > 0:
            def after_update_cb(result):
                if result[0] == 'OK':
                    updated_fullnames = result[1]
                    if len(updated_fullnames) > 0:
                        self.server.reboot_nodes_after_image_change(
                            requester, final_task_cb, *updated_fullnames
                        )
                    else:
                        final_task_cb()
                else:
                    final_task_cb()
            blocking_func = functools.partial(
                    self.blocking.update_default_images,
                    requester, update_info=update_info)
            handle_client_registry_conf_issues(requester, blocking_func, after_update_cb)
        else:
            final_task_cb()

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
        return self.get_images_per_fullnames((image_fullname,))[0]

    def get_images_per_fullnames(self, fullnames):
        missing = set(fullnames) - set(self.images)
        if len(missing) > 0:
            # an image was probably downloaded using podman commands
            # (e.g. by the blocking process), main process does not know it yet
            for image_fullname in missing:
                self.registry.refresh_cache_for_image(image_fullname)
            self.resync_from_registry()
        return tuple(self.images[fullname] for fullname in fullnames)

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
        found = self.images.get(fullname)
        if found is None and not self.user_has_images(username):
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

    def user_has_images(self, username):
        for image in self.images.values():
            if image.user == username:
                return True
        return False

    def get_user_unused_image_from_name(self, requester, image_name):
        image = self.get_user_image_from_name(requester, image_name)
        if image:  # otherwise issue is already reported
            if image.in_use():
                requester.stderr.write(
                    "Sorry, cannot proceed because the image is in use.\n"
                )
                return None
        return image

    def get_images_in_use(self):
        return set(self.db.execute("SELECT DISTINCT image FROM nodes")["image"])

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

    def get_filesystem(self, image_id):
        return self.filesystems[image_id]

    def get_clones_of_default_images(self, requester, node_set):
        # returns a tuple of 3 values:
        # 1: whether the request was valid
        # 2: whether some new images have been cloned by this procedure
        # 3: a dictionary indicating the defaut image name for each input node name
        username = requester.get_username()
        if not username:
            return False, False, {}  # client already disconnected, give up
        nodes = self.server.nodes.parse_node_set(requester, node_set, allow_empty=True)
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
            if ':' not in image_name:
                image_name = image_name + ':latest'
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
