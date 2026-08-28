from __future__ import annotations

from collections import defaultdict
import typing

from walt.common.formatting import format_sentence, format_sentence_about_nodes
from walt.common.tools import format_image_fullname, parse_image_fullname
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
from walt.server.processes.main.images.show import show
from walt.server.processes.main.images.squash import squash
from walt.server.processes.main.images.store import NodeImageStore
from walt.server.processes.main.images.tabular import get_user_tabular_data
from walt.server.processes.main.images.webapi import web_api_list_images
from walt.server.processes.main.nodes.reboot import wf_reboot_nodes
from walt.server.tools import get_temp_image_fullname
from walt.server.workflow import Workflow

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server

# About terminology: See comment about it in image.py.
MSG_BOOT_FREE_IMAGE = """\
%s will now boot a special 'waltplatform/<model>-free' OS image;
it(they) will appear as 'free' when users run "walt node show".\
"""
MSG_BOOT_USER_IMAGE = \
    lambda image_name: f"%s will now boot your OS image '{image_name}'."

MSG_INCOMPATIBLE_MODELS = """\
Sorry, this image is not compatible with %s.
"""


class NodeImageManager:
    def __init__(self, server: Server):
        self.server = server
        self.db = server.db
        self.blocking = server.blocking
        self.dhcpd = server.dhcpd
        self.named = server.named
        self.registry = server.registry
        self.store = NodeImageStore(server)

    def show(self, requester, **kwargs):
        return show(requester, self, **kwargs)

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

    def get_user_tabular_data(self, requester, username, refresh, fields):
        return get_user_tabular_data(
            self.db, self.store, requester, username, refresh, fields
        )

    def web_api_list_images(self, *args):
        return web_api_list_images(self.db, self.store, *args)

    def rename(self, requester, image_name, new_name):
        return rename(self.store, self.registry, requester, image_name, new_name)

    def remove(self, requester, image_name):
        return remove(self.store, self.registry, requester, image_name)

    def duplicate(self, requester, image_name, new_name):
        return duplicate(self.store, self.registry, requester, image_name, new_name)

    def update_default_images(self, requester, task):
        task.set_async()  # result will be available later
        return self.store.update_default_images(requester, task.return_result)

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
            if not self.has_image(requester, image_name):
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

    def has_image(self, requester, image_name, expected=True):
        image = self.store.get_user_image_from_name(
            requester, image_name, expected=expected
        )
        return image is not None

    def set_image(self, requester, task, node_set, image_name_or_keyword):
        nodes = self.server.nodes.parse_node_set(
                requester, node_set, allow_empty=True)
        if nodes is None:  # issue already reported
            return False
        if image_name_or_keyword in ("default", "free"):
            valid, image_per_node_name = self._analyse_set_image_keyword(
                    requester, nodes, image_name_or_keyword)
        else:
            valid, image_per_node_name = self._analyse_set_image_name(
                    requester, nodes, image_name_or_keyword)
        if not valid:
            return False
        ignored_names = set()
        image_fullnames = {}
        for node in nodes:
            image_fullname = image_per_node_name[node.name]
            if node.image == image_fullname:
                ignored_names.add(node.name)
            else:
                image_fullnames[node.mac] = image_fullname
        is_free = (image_name_or_keyword == "free")
        is_default = (image_name_or_keyword == "default")
        if len(ignored_names) > 0:
            if is_free:
                sentence = "%s: ignored, already free."
            else:
                sentence = "%s: ignored, already using this image."
            requester.stdout.write(
                format_sentence_about_nodes(sentence, ignored_names) + "\n"
            )
        ok_names = set(n.name for n in nodes if n.name not in ignored_names)
        if len(ok_names) > 0:
            # let's update the database about which node is mounting what
            for node_mac, image_fullname in image_fullnames.items():
                self.db.update("nodes", "mac", mac=node_mac, image=image_fullname)
                self.server.nodes.powersave.handle_event(
                    "set_image", node_mac, is_free
                )
            self.db.commit()
            # inform user
            if is_default:
                node_names_per_image = defaultdict(list)
                for node_name, fullname in image_per_node_name.items():
                    if node_name not in ok_names:
                        continue
                    node_names_per_image[fullname].append(node_name)
                for fullname, node_names in node_names_per_image.items():
                    _, _, image_name = parse_image_fullname(image_fullname)
                    sentence = MSG_BOOT_USER_IMAGE(image_name)
                    message = format_sentence_about_nodes(sentence, node_names)
            else:
                if is_free:
                    sentence = MSG_BOOT_FREE_IMAGE
                else:
                    sentence = MSG_BOOT_USER_IMAGE(image_name_or_keyword)
                message = format_sentence_about_nodes(sentence, ok_names)
            # turn the client task to async mode and run a workflow
            task.set_async()
            wf = Workflow([self.server.exports.wf_update,
                           self.dhcpd.wf_update,
                           self.named.wf_update,
                           self._wf_end_of_set_image],
                          requester = requester,
                          task = task,
                          message = message)
            wf.run()
            return True
        return True

    def _analyse_set_image_keyword(self, requester, nodes, keyword):
        # get info about images clones, possibly clone them
        valid, _, image_per_node_name = (
            self.store.get_clones_of_images_for_nodes(
                requester,
                nodes,
                keyword,
            )
        )
        return valid, image_per_node_name

    def _analyse_set_image_name(self, requester, nodes, image_name):
        image = self.store.get_user_image_from_name(requester, image_name)
        if image is None:
            return False, {}
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
            return False, {}
        image_per_node_name = { node.name: image.fullname
                                for node in nodes }
        return True, image_per_node_name

    def set_free_nodes_image(self, requester, task,
                             node_model, image_name_or_default):
        # check if node_model is valid
        nodes = self.server.devices.get_multiple_device_info(
                    "d.type = 'node' and n.model = %s", (node_model,))
        if len(nodes) == 0:
            requester.stderr.write(
                f"The node model specified '{node_model}' seems wrong.\n"
                "There is no node of this model in the platform.\n")
            return False
        # compute src_image_fullname
        if image_name_or_default == "default":
            default_image = self.store.get_default_image_fullname(node_model)
            src_image_fullname = default_image
        else:
            image_name = image_name_or_default
            image = self.store.get_user_image_from_name(
                        requester, image_name)
            if image is None:
                return False
            if node_model not in image.get_node_models():
                requester.stderr.write(
                    f"Sorry '{node_model}' is not one of the node models "
                    f"'{image_name}' declares compatibility with.\n"
                )
                return False
            src_image_fullname = image.fullname
        # associate the image to free nodes
        free_image = self.store.get_free_image_fullname(node_model)
        requester.stdout.write(
            f"Tagging '{src_image_fullname}' as '{free_image}'.\n"
        )
        self.registry.tag(src_image_fullname, free_image)
        # filter nodes to get only free ones
        free_nodes = nodes[nodes.image == free_image]
        # reexport image and reboot free nodes
        task.set_async()
        steps = [self.server.exports.wf_update]
        env = dict(
              requester=requester,
              task=task,
        )
        if len(free_nodes) > 0:
            steps += [wf_reboot_nodes]
            env.update(
                  reboot_cause="free image change",
                  server=self.server,
                  nodes=free_nodes,
                  hard_only=False,
            )
        steps += [self._wf_end_set_free_nodes_image]
        wf = Workflow(steps, **env)
        wf.run()

    def _wf_end_set_free_nodes_image(self, wf, task, **env):
        # unblock the client
        task.return_result(True)
        wf.next()

    def _wf_end_of_set_image(self, wf, requester, task, message, **env):
        # inform requester
        requester.stdout.write(message + "\n")
        # unblock the client
        task.return_result(True)
        wf.next()

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
        session = ImageShellSession(self.server, image, task_label)
        return session

    def update_hub_metadata(self, context, waltplatform_user):
        return update_hub_metadata(
            blocking=self.blocking,
            requester=context.requester,
            task=context.task,
            waltplatform_user=waltplatform_user,
        )

    def create_build_session(self, requester, image_name, **info):
        username = requester.get_username()
        if not validate_image_name(requester, image_name):
            return None
        if "with_node_name" in info:
            with_node_name = info["with_node_name"]
            node = self.db.select_unique(
                            "devices",
                            name=with_node_name
            )
            info["with_node_mac"] = node.mac
        image_fullname = format_image_fullname(username, image_name)
        image_overwrite = self.has_image(
                requester, image_name, expected=None)
        if image_overwrite and info.get("force", False) is False:
            msg = self.store.get_image_overwrite_warning(image_fullname)
            requester.stderr.write(msg)
        session = ImageBuildSession(
                self.server, image_fullname, image_overwrite,
                username=username,
                **info
        )
        return session
