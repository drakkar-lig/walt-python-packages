from collections import defaultdict
from walt.client.timeout import start_timeout, stop_timeout
from walt.client.apiobject.base import APIObjectBase, APISetOfItemsClassFactory, \
                                       APIItemClassFactory, APIItemInfoCache, \
                                       APICommentedString
from walt.client.apiobject.images import APIImageBase, get_image_from_name, \
                                         update_image_cache, \
                                         get_image_object_from_fullname
from walt.client.apiobject.config import APINodeConfig
from walt.client.apitools import silent_server_link, get_devices_names
from walt.client.config import conf

EXCEPTION_NODE_HAS_LOGS = """\
Removing a node with logs without the force parameter is not allowed"""

class NodeHasLogsException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_NODE_HAS_LOGS)

EXCEPTION_NODE_NOT_OWNED = """\
Using a node owned by someone else without the force parameter is not allowed"""

class NodeNotOwnedException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_NODE_NOT_OWNED)

EXCEPTION_PARAMETER_NOT_AN_IMAGE = """\
The specified parameter is not a WalT image"""

class ParameterNotAnImageException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_PARAMETER_NOT_AN_IMAGE)

class APINodeInfoCache(APIItemInfoCache):
    def __init__(self):
        super().__init__(show_aliases=False)
    def do_refresh(self, server):
        nodes_info = server.get_nodes_info('all-nodes')
        # populate attributes
        self.info_per_id = {}
        self.id_per_name = {}
        self.names_per_id = defaultdict(set)
        for info in nodes_info:
            name = info.pop('name')
            node_id = info['mac']
            self.id_per_name[name] = node_id
            self.info_per_id[node_id] = info
            self.names_per_id[node_id].add(name)
    def do_remove_item(self, server, item_name):
        node_id = self.id_per_name[item_name]
        node_info = self.info_per_id[node_id]
        is_virtual = node_info['virtual']
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
        return ','.join(node_names)
    @staticmethod
    def get_image_name_or_default(image):
        if isinstance(image, str):
            if image == 'default':
                image_name_or_default = 'default'
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
    def boot_image(nodes, image, force=False):
        image_name_or_default = Tools.get_image_name_or_default(image)
        for n in nodes:
            n._check_owned_or_force(force)
        nodeset = Tools.get_comma_nodeset(nodes)
        with silent_server_link() as server:
            if not server.set_image(nodeset, image_name_or_default):
                return
            server.reboot_nodes(nodeset)
        # update node info cache to print the correct image name
        # on this node
        __info_cache__.refresh()
        # update image info cache (the <image>.in_use flag may have changed)
        update_image_cache()

class APINodeFactory:
    __nodes_per_mac__ = {}
    @staticmethod
    def create(in_node_name):
        node_mac = __info_cache__[in_node_name]['mac']
        api_node = APINodeFactory.__nodes_per_mac__.get(node_mac)
        if api_node is not None:
            return api_node
        is_virtual = __info_cache__[in_node_name]['virtual']
        if is_virtual:
            item_label = 'virtual node'
        else:
            item_label = 'node'
        item_cls = APIItemClassFactory.create(__info_cache__, in_node_name,
                                item_label, APINodeBase, APISetOfNodesFactory)
        class APINode(item_cls, APINodeBase):
            def __get_remote_info__(self):
                info = super().__get_remote_info__()
                owner = info['image'].split('/')[0]
                if owner == conf.walt.username:
                    owner = APICommentedString(owner, 'yourself')
                elif owner == 'waltplatform':
                    owner = APICommentedString(owner, 'node is free')
                info.update(owner = owner)
                del info['conf']
                info['image'] = get_image_object_from_fullname(info['image'])
                return info
            def __volatile_attrs__(self):
                return ('booted',)
            def __force_refresh__(self):
                __info_cache__.refresh()
            @property
            def config(self):
                return APINodeConfig(self._get_config, self._set_config)
            def _get_config(self):
                with silent_server_link() as server:
                    dev_configs = server.get_device_config_data(self.name)
                    return dev_configs[self.name]['settings']
            def _set_config(self, setting_name, setting_value):
                with silent_server_link() as server:
                    server.set_device_config(self.name, (f'{setting_name}={setting_value}',))
            def _check_owned_or_force(self, force=False):
                # check whether user owns the node
                # if the node is free (user 'waltplatform'), that's OK too.
                if not force and self.owner not in (conf.walt.username, 'waltplatform'):
                    raise NodeNotOwnedException()
            def reboot(self, force=False, hard_only=False):
                """Reboot this node"""
                self._check_owned_or_force(force)
                with silent_server_link() as server:
                    server.reboot_nodes(self.name, hard_only)
            def wait(self, timeout_secs=-1):
                """Wait until node is booted"""
                with silent_server_link() as server:
                    if timeout_secs > 0:
                        start_timeout(timeout_secs)
                    server.wait_for_nodes(self.name)
                    if timeout_secs > 0:
                        stop_timeout()
            def _remove_or_forget(self, force=False):
                self._check_owned_or_force(force)
                with silent_server_link() as server:
                    if not force:
                        # note: do not count logs of "*console" streams
                        logs_cnt = server.count_logs(
                                history = (None, None),
                                issuers = set([self.name]))
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
                Tools.boot_image((self,), image, force=force)
        api_node = APINode()
        APINodeFactory.__nodes_per_mac__[node_mac] = api_node
        __info_cache__.register_obj(api_node)
        return api_node

class APISetOfNodesFactory:
    @classmethod
    def create(item_set_factory, in_names):
        item_set_cls = APISetOfItemsClassFactory.create(
            __info_cache__, in_names, 'node', APINodeBase,
            APINodeFactory, APISetOfNodesBase, item_set_factory)
        class APISetOfNodes(item_set_cls, APISetOfNodesBase):
            """Set of WalT nodes"""
            def _get_walt_nodeset(self):
                node_names = set(n.name for n in self)
                return ','.join(node_names)
            def reboot(self, force=False, hard_only=False):
                """Reboot all nodes of this set"""
                for n in self:
                    n._check_owned_or_force(force)
                with silent_server_link() as server:
                    server.reboot_nodes(Tools.get_comma_nodeset(self), hard_only)
            def wait(self, timeout_secs=-1):
                """Wait until all nodes of this set are booted"""
                with silent_server_link() as server:
                    if timeout_secs > 0:
                        start_timeout(timeout_secs)
                    server.wait_for_nodes(Tools.get_comma_nodeset(self))
                    if timeout_secs > 0:
                        stop_timeout()
            def boot(self, image, force=False):
                """Boot the specified image on all nodes of this set"""
                Tools.boot_image(self, image, force=force)
        return APISetOfNodes()

class APINodesSubModule(APIObjectBase):
    """API submodule for WALT nodes"""
    def get_nodes(self, node_set='all-nodes'):
        """Return nodes of the platform"""
        with silent_server_link() as server:
            names = get_devices_names(server, node_set,
                            allowed_device_set = 'all-nodes')
            if names is None:
                raise Exception('''Invalid set of nodes specified.''')
        return APISetOfNodesFactory.create(names)
    def create_vnode(self, node_name):
        """Create a virtual node"""
        with silent_server_link() as server:
            server.create_vnode(node_name)
            nodes_info = server.get_nodes_info(node_name)
        __info_cache__.refresh()    # detect the new node
        return APINodeFactory.create(node_name)

def get_api_nodes_submodule():
    return APINodesSubModule()
