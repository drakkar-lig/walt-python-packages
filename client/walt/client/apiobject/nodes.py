from collections import defaultdict

from walt.client.apiobject.base import (
    APICommentedString,
    APIItemClassFactory,
    APIItemInfoCache,
    APIObjectBase,
    APISetOfItemsClassFactory,
)
from walt.client.apiobject.config import APINodeConfig
from walt.client.apiobject.images import (
    APIImageBase,
    get_image_from_name,
    get_image_object_from_fullname,
    update_image_cache,
)
from walt.client.apitools import get_devices_names, silent_server_link
from walt.client.config import conf
from walt.client.exceptions import (
    NodeAlreadyOwnedException,
    NodeHasLogsException,
    NodeNotOwnedException,
    OpAppliesNodeOwnedException,
    ParameterNotAnImageException,
)
from walt.client.timeout import timeout_context


class APINodeInfoCache(APIItemInfoCache):
    def __init__(self):
        super().__init__(show_aliases=False)

    def do_refresh(self, server):
        nodes_info = server.get_nodes_info("all-nodes")
        # populate attributes
        self.info_per_id = {}
        self.id_per_name = {}
        self.names_per_id = defaultdict(set)
        for info in nodes_info:
            name = info.pop("name")
            node_id = info["mac"]
            self.id_per_name[name] = node_id
            self.info_per_id[node_id] = info
            self.names_per_id[node_id].add(name)

    def do_remove_item(self, server, item_name):
        node_id = self.id_per_name[item_name]
        node_info = self.info_per_id[node_id]
        is_virtual = node_info["virtual"]
        if is_virtual:
            return server.remove_vnode(item_name)
        else:
            return server.forget(item_name)

    def do_rename_item(self, server, item_name, new_item_name):
        return server.rename(item_name, new_item_name)


__info_cache__ = APINodeInfoCache()


class APINodeBase:
    """Base class of all APINode classes, for use in isinstance()"""

    pass


class APISetOfNodesBase:
    """Base class of all APISetOfNodes classes, for use in isinstance()"""

    pass


class Tools:
    @staticmethod
    def get_comma_nodeset(nodes):
        node_names = set(n.name for n in nodes)
        return ",".join(node_names)

    @staticmethod
    def get_image_name_or_default(image):
        if isinstance(image, str):
            if image == "default":
                image_name_or_default = "default"
            else:
                image = get_image_from_name(image)
                image_name_or_default = image.name
        else:
            if isinstance(image, APIImageBase):
                image_name_or_default = image.name
            else:
                raise ParameterNotAnImageException()
        return image_name_or_default

    @staticmethod
    def boot_image(nodes, image, cause, force=False, ownership_mode="owned-or-free"):
        image_name_or_default = Tools.get_image_name_or_default(image)
        for n in nodes:
            n._check_owned_or_force(force, ownership_mode)
        nodeset = Tools.get_comma_nodeset(nodes)
        with silent_server_link() as server:
            if not server.set_image(nodeset, image_name_or_default):
                return
            server.reboot_nodes(nodeset, cause=cause)
        # update node info cache to print the correct image name
        # on this node
        __info_cache__.refresh()
        # update image info cache (the <image>.in_use flag may have changed)
        update_image_cache()

    @staticmethod
    def acquire(nodes, force=False):
        for n in nodes:
            n._check_owned_or_force(force=force, mode="free-or-not-owned")
        nodeset = Tools.get_comma_nodeset(nodes)
        with silent_server_link() as server:
            _, _, image_per_node = server.get_clones_of_default_images(nodeset)
            # revert image_per_node dictionary
            from collections import defaultdict

            nodes_per_image = defaultdict(list)
            for node, image in image_per_node.items():
                nodes_per_image[image].append(node)
            # associate nodes with appropriate image
            for image, nodes in nodes_per_image.items():
                image_node_set = ",".join(nodes)
                if not server.set_image(image_node_set, image):
                    return  # unexpected issue
            # reboot
            server.reboot_nodes(nodeset, cause="acquire")
        # update node info cache to print the correct image name
        # on this node
        __info_cache__.refresh()
        # update image info cache (the <image>.in_use flag may have changed)
        update_image_cache()


class APINodeFactory:
    __nodes_per_mac__ = {}

    @staticmethod
    def create(in_node_name):
        node_mac = __info_cache__[in_node_name]["mac"]
        api_node = APINodeFactory.__nodes_per_mac__.get(node_mac)
        if api_node is not None:
            return api_node
        is_virtual = __info_cache__[in_node_name]["virtual"]
        if is_virtual:
            item_label = "virtual node"
        else:
            item_label = "node"
        item_cls = APIItemClassFactory.create(
            __info_cache__, in_node_name, item_label, APINodeBase, APISetOfNodesFactory
        )

        class APINode(item_cls, APINodeBase):
            def __get_remote_info__(self):
                info = super().__get_remote_info__()
                owner = info["image"].split("/")[0]
                if owner == conf.walt.username:
                    owner = APICommentedString(owner, "yourself")
                elif owner == "waltplatform":
                    owner = APICommentedString(owner, "node is free")
                info.update(owner=owner, device_type="node")
                del info["conf"]
                info["image"] = get_image_object_from_fullname(info["image"])
                return info

            def __volatile_attrs__(self):
                return ("booted",)

            def __force_refresh__(self):
                __info_cache__.refresh()

            @property
            def config(self):
                return APINodeConfig(self._get_config, self._set_config)

            def _get_config(self):
                with silent_server_link() as server:
                    dev_configs = server.get_device_config_data(self.name)
                    return dev_configs[self.name]["settings"]

            def _set_config(self, setting_name, setting_value):
                with silent_server_link() as server:
                    server.set_device_config(
                        self.name, (f"{setting_name}={setting_value}",)
                    )

            def _check_owned_or_force(self, force=False, mode="owned-or-free"):
                if mode == "free-or-not-owned" and self.owner == conf.walt.username:
                    raise NodeAlreadyOwnedException()
                if mode == "owned" and self.owner != conf.walt.username:
                    raise OpAppliesNodeOwnedException()
                if (
                    mode in ("owned-or-free", "free-or-not-owned")
                    and not force
                    and self.owner not in (conf.walt.username, "waltplatform")
                ):
                    raise NodeNotOwnedException()

            def reboot(self, force=False, hard_only=False):
                """Reboot this node"""
                self._check_owned_or_force(force)
                with silent_server_link() as server:
                    server.reboot_nodes(self.name, hard_only=hard_only)

            def wait(self, timeout=-1):
                """Wait until node is booted"""
                with silent_server_link() as server:
                    with timeout_context(timeout):
                        server.wait_for_nodes(self.name)

            def get_logs(self, realtime=False, history=None, timeout=-1):
                """Iterate over historical or realtime logs"""
                from walt.client.apiobject.logs import get_api_logs_submodule

                api_logs = get_api_logs_submodule()
                return api_logs.get_logs(
                    realtime=realtime, history=history, issuers=self, timeout=timeout
                )

            def _remove_or_forget(self, force=False):
                self._check_owned_or_force(force)
                with silent_server_link() as server:
                    if not force:
                        # note: do not count logs of "*console" streams
                        logs_cnt = server.count_logs(
                            history=(None, None),
                            issuers=set([self.name]),
                            streams="$(?<!console)",
                        )
                        if logs_cnt > 0:
                            raise NodeHasLogsException()
                # ok, do it
                self.__remove_from_cache__()
                # forget in factory
                del APINodeFactory.__nodes_per_mac__[node_mac]

            if is_virtual:

                def remove(self, force=False):
                    return self._remove_or_forget(force)

            else:

                def forget(self, force=False):
                    return self._remove_or_forget(force)

            def rename(self, new_name, force=False):
                self._check_owned_or_force(force)
                return self.__rename_in_cache__(new_name)

            def boot(self, image, force=False):
                """Boot the specified WalT image"""
                Tools.boot_image((self,), image, "image change", force=force)

            def release(self):
                """Release ownership of this node"""
                Tools.boot_image((self,), "default", "release", ownership_mode="owned")

            def acquire(self, force=False):
                """Get ownership of this node"""
                Tools.acquire((self,), force=force)

        api_node = APINode()
        APINodeFactory.__nodes_per_mac__[node_mac] = api_node
        __info_cache__.register_obj(api_node)
        return api_node


class APISetOfNodesFactory:
    @classmethod
    def create(item_set_factory, in_names):
        item_set_cls = APISetOfItemsClassFactory.create(
            __info_cache__,
            in_names,
            "node",
            APINodeBase,
            APINodeFactory,
            APISetOfNodesBase,
            item_set_factory,
        )

        class APISetOfNodes(item_set_cls, APISetOfNodesBase):
            """Set of WalT nodes"""

            def _get_walt_nodeset(self):
                node_names = set(n.name for n in self)
                return ",".join(node_names)

            def reboot(self, force=False, hard_only=False):
                """Reboot all nodes of this set"""
                for n in self:
                    n._check_owned_or_force(force)
                with silent_server_link() as server:
                    server.reboot_nodes(Tools.get_comma_nodeset(self),
                                        hard_only=hard_only)

            def wait(self, timeout=-1):
                """Wait until all nodes of this set are booted"""
                with silent_server_link() as server:
                    with timeout_context(timeout):
                        server.wait_for_nodes(Tools.get_comma_nodeset(self))

            def get_logs(self, realtime=False, history=None, timeout=-1):
                """Iterate over historical or realtime logs"""
                from walt.client.apiobject.logs import get_api_logs_submodule

                api_logs = get_api_logs_submodule()
                return api_logs.get_logs(
                    realtime=realtime, history=history, issuers=self, timeout=timeout
                )

            def boot(self, image, force=False):
                """Boot the specified image on all nodes of this set"""
                Tools.boot_image(self, image, "image change", force=force)

            def release(self):
                """Release ownership of all nodes in this set"""
                Tools.boot_image(self, "default", "release", ownership_mode="owned")

            def acquire(self, force=False):
                """Get ownership of all nodes in this set"""
                Tools.acquire(self, force=force)

        return APISetOfNodes()


class APINodesSubModule(APIObjectBase):
    """API submodule for WALT nodes"""

    def get_nodes(self, node_set="all-nodes"):
        """Return nodes of the platform"""
        with silent_server_link() as server:
            names = get_devices_names(server, node_set, allowed_device_set="all-nodes")
            if names is None:
                raise Exception("""Invalid set of nodes specified.""")
        return APISetOfNodesFactory.create(names)

    def create_vnode(self, node_name):
        """Create a virtual node"""
        with silent_server_link() as server:
            server.create_vnode(node_name)
        __info_cache__.refresh()  # detect the new node
        return APINodeFactory.create(node_name)


def get_api_nodes_submodule():
    return APINodesSubModule()
