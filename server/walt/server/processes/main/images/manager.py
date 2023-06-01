from __future__ import annotations

import typing

from walt.common.formatting import format_sentence, format_sentence_about_nodes
from walt.common.tools import format_image_fullname
from walt.server.processes.main.images.build import ImageBuildSession
from walt.server.processes.main.images.clone import clone
from walt.server.processes.main.images.duplicate import duplicate
from walt.server.processes.main.images.fixowner import fix_owner
from walt.server.processes.main.images.image import validate_image_name
from walt.server.processes.main.images.metadata import update_hub_metadata
from walt.server.processes.main.images.publish import publish
from walt.server.processes.main.images.remove import remove
from walt.server.processes.main.images.rename import rename
from walt.server.processes.main.images.search import search
from walt.server.processes.main.images.shell import ImageShellSession
from walt.server.processes.main.images.squash import squash
from walt.server.processes.main.images.store import NodeImageStore
from walt.server.processes.main.images.tabular import get_tabular_data
from walt.server.processes.main.workflow import Workflow

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server

# About terminology: See comment about it in image.py.
MSG_BOOT_DEFAULT_IMAGE = """\
%s will now boot its(their) default image \
(other users will see it(they) is(are) 'free')."""
MSG_INCOMPATIBLE_MODELS = """\
Sorry, this image is not compatible with %s.
"""


class NodeImageManager:
    def __init__(self, server: Server):
        self.server = server
        self.db = server.db
        self.blocking = server.blocking
        self.dhcpd = server.dhcpd
        self.registry = server.registry
        self.store = NodeImageStore(server)

    def prepare(self):
        pass

    def update(self, startup=False):
        self.store.resync_from_db()
        self.store.trigger_update_image_mounts()

    def search(self, requester, task, keyword, tty_mode):
        return search(self.blocking, requester, task, keyword, tty_mode)

    def clone(self, **kwargs):
        return clone(blocking=self.blocking, **kwargs)

    def publish(self, requester, task, image_name, **kwargs):
        return publish(self.store, self.blocking, requester, task, image_name, **kwargs)

    def squash(self, requester, task_callback, image_name, confirmed):
        return squash(
            self.store, self.blocking, requester, task_callback, image_name, confirmed
        )

    def get_tabular_data(self, requester, username, refresh, fields):
        return get_tabular_data(
            self.db, self.store, requester, username, refresh, fields
        )

    def rename(self, requester, image_name, new_name):
        return rename(self.store, self.registry, requester, image_name, new_name)

    def remove(self, requester, image_name):
        return remove(self.store, self.registry, requester, image_name)

    def duplicate(self, requester, image_name, new_name):
        return duplicate(self.store, self.registry, requester, image_name, new_name)

    def validate_cp_entity(self, requester, image_name, index, **info):
        if image_name == "booted-image":
            username = requester.get_username()
            image_fullname = info["node_image"]
            image = self.store[image_fullname]
            if image.user != username:
                # modifying the image of others is not possible
                requester.stderr.write(
                    "Cannot proceed because the booted image does not belong to you.\n"
                )
                return "FAILED"
            if self.store.warn_if_would_reboot_nodes(requester, image_fullname):
                return "NEEDS_CONFIRM"
        else:
            if not self.has_image(requester, image_name, False):
                return "FAILED"
            if index == 1:  # image is destination, it will be modified
                if self.store.warn_if_would_reboot_nodes(requester, image_name):
                    return "NEEDS_CONFIRM"
        return "OK"

    def get_image_filesystem(self, requester, image_name):
        image = self.store.get_user_image_from_name(requester, image_name)
        if image is None:
            return None
        return image.filesystem

    def get_cp_entity_filesystem(self, requester, image_name, **info):
        if image_name == "booted-image":
            image_fullname = info["node_image"]
            return self.store[image_fullname].filesystem
        else:
            return self.get_image_filesystem(requester, image_name)

    def get_cp_entity_attrs(self, requester, image_name, **info):
        return dict(image_name=image_name)

    def fix_owner(self, requester, other_user):
        fix_owner(self.store, self.registry, requester, other_user)

    def cleanup(self):
        # un-mount images
        self.store.cleanup()

    def has_image(self, requester, image_name, default_allowed, expected=True):
        if default_allowed and image_name == "default":
            return True
        else:
            image = self.store.get_user_image_from_name(
                requester, image_name, expected=expected
            )
            return image is not None

    def set_image(self, requester, nodes, image_name):
        is_default = image_name == "default"
        # if image tag is specified, let's get its fullname
        if not is_default:
            image = self.store.get_user_image_from_name(requester, image_name)
            if image is None:
                return False
            image_compatible_models = set(image.get_node_models())
            node_models = set(node.model for node in nodes)
            incompatible_models = node_models - image_compatible_models
            if len(incompatible_models) > 0:
                sentence = format_sentence(
                    MSG_INCOMPATIBLE_MODELS,
                    incompatible_models,
                    None,
                    "node model",
                    "node models",
                )
                requester.stderr.write(sentence)
                return False
            ignored_names = set(
                node.name for node in nodes if node.image == image.fullname
            )
            image_fullnames = {
                node.mac: image.fullname
                for node in nodes
                if node.name not in ignored_names
            }
        else:
            ignored_names = set()
            image_fullnames = {}
            # since the 'default' keyword was specified, we might have to associate
            # different images depending on the type of each WalT node.
            # we compute the appropriate image fullname here.
            for node in nodes:
                image_fullname = self.store.get_default_image_fullname(node.model)
                if node.image == image_fullname:
                    ignored_names.add(node.name)
                else:
                    image_fullnames[node.mac] = image_fullname
        ok_names = set(n.name for n in nodes if n.name not in ignored_names)
        if len(ok_names) > 0:
            # let's update the database about which node is mounting what
            for node_mac, image_fullname in image_fullnames.items():
                self.db.update("nodes", "mac", mac=node_mac, image=image_fullname)
                self.server.nodes.powersave.handle_event(
                    "set_image", node_mac, is_default
                )
            self.db.commit()
            wf = Workflow([self.store.wf_update_image_mounts, self.dhcpd.wf_update])
            wf.run()
            # inform requester
            if is_default:
                sentence = MSG_BOOT_DEFAULT_IMAGE
            else:
                sentence = "%s will now boot " + image_name + "."
            requester.stdout.write(
                format_sentence_about_nodes(sentence, ok_names) + "\n"
            )
        if len(ignored_names) > 0:
            requester.stdout.write(
                format_sentence_about_nodes(
                    "%s: ignored, it(they) is(are) already using this image.",
                    ignored_names,
                )
                + "\n"
            )
        return True

    def create_shell_session(self, requester, image_name, task_label):
        image = self.store.get_user_image_from_name(requester, image_name)
        if image is None:
            return None
        if not image.editable:
            requester.stderr.write(
                (
                    "Cannot open image %(image_name)s because it has already reached"
                    " its max number of layers.\n"
                    + "(tip: walt image squash %(image_name)s)\n"
                )
                % dict(image_name=image_name)
            )
            return None
        if image.task_label:
            requester.stderr.write(
                "Cannot open image %s because a %s is already running.\n"
                % (image_name, image.task_label)
            )
            return None
        session = ImageShellSession(self.store, image, task_label)
        return session

    def update_hub_metadata(self, context, waltplatform_user):
        return update_hub_metadata(
            blocking=self.blocking,
            requester=context.requester,
            task=context.task,
            waltplatform_user=waltplatform_user,
        )

    def create_build_session(self, requester, image_name, **info):
        if not validate_image_name(requester, image_name):
            return None
        image_fullname = format_image_fullname(requester.get_username(), image_name)
        image_overwrite = self.has_image(requester, image_name, False, expected=None)
        if image_overwrite:
            msg = self.store.get_image_overwrite_warning(image_fullname)
            requester.stderr.write(msg)
        session = ImageBuildSession(
            self.blocking, self.store, image_fullname, image_overwrite, **info
        )
        return session
