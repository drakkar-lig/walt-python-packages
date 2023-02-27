from walt.client.apiobject.base import APIObjectBase, APIObjectRegistryClass, CommentedString
from walt.client.apitools import snakecase, create_names_dict
from walt.client.link import ClientToServerLink
from walt.client.config import conf
from walt.client.timeout import start_timeout, stop_timeout
from walt.common.tools import SilentBusyIndicator
from contextlib import contextmanager

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

class AlreadyInSetException(Exception):
    pass

@contextmanager
def silent_server_link():
    indicator = SilentBusyIndicator()
    with ClientToServerLink(busy_indicator = indicator) as server:
        yield server

class APINodeImplBase(APIObjectBase):
    """Base class of all APINodeImpl classes, for use in isinstance()"""
    pass

class APINode:
    _known = {}
    _deleted = set()
    def __new__(cls, node_info):
        node_name = node_info['name']
        is_virtual = node_info['virtual']
        def check_deleted():
            if node_name in APINode._deleted:
                raise ReferenceError('This node is no longer valid! (was forgotten)')
        if is_virtual:
            doc = 'virtual node ' + node_name
        else:
            doc = 'node ' + node_name
        if node_name not in APINode._known:
            class APINodeImpl(APINodeImplBase):
                __doc__ = doc
                @property
                def name(self):
                    return node_name    # perf: avoid call to __get_remote_info__()
                def __get_remote_info__(self):
                    check_deleted()
                    with silent_server_link() as server:
                        nodes_info = server.get_nodes_info(node_name)
                    info = nodes_info[0]
                    owner = info['image'].split('/')[0]
                    if owner == conf.walt.username:
                        owner = CommentedString(owner, 'yourself')
                    elif owner == 'waltplatform':
                        owner = CommentedString(owner, 'node is free')
                    info.update(owner = owner)
                    return info
                def _check_owned_or_force(self, force=False):
                    if not force and self.owner != conf.walt.username:
                        raise NodeNotOwnedException()
                def reboot(self, force=False, hard_only=False):
                    """Reboot this node"""
                    self._check_owned_or_force(force)
                    with silent_server_link() as server:
                        server.reboot_nodes(node_name, hard_only)
                def wait(self, timeout_secs=-1):
                    """Wait until node is booted"""
                    with silent_server_link() as server:
                        if timeout_secs > 0:
                            start_timeout(timeout_secs)
                        server.wait_for_nodes(node_name)
                        if timeout_secs > 0:
                            stop_timeout()
                def _remove_or_forget(self, force=False):
                    with silent_server_link() as server:
                        self._check_owned_or_force(force)
                        if not force:
                            logs_cnt = server.count_logs(
                                    history = (None, None),
                                    senders = set([node_name]))
                            if logs_cnt > 0:
                                raise NodeHasLogsException()
                        # ok, do it
                        if is_virtual:
                            server.remove_vnode(node_name)
                        else:
                            server.forget(node_name)
                    APINode._deleted.add(node_name)
                if is_virtual:
                    def remove(self, force=False):
                        """Remove this virtual node"""
                        return self._remove_or_forget(force)
                else:
                    def forget(self, force=False):
                        """Forget this node"""
                        return self._remove_or_forget(force)
                def __add__(self, other_node):
                    new_set = APINodesDict({})
                    new_set += other_node
                    new_set += self
                    return new_set
            APINode._known[node_name] = APINodeImpl()
        return APINode._known[node_name]

class APINodesDict:
    def __new__(cls, d):
        class APINodesDictImpl(APIObjectRegistryClass(d)):
            """Set of WalT nodes"""
            def create(self, node_name):
                """Create a virtual node"""
                with silent_server_link() as server:
                    server.create_vnode(node_name)
                    nodes_info = server.get_nodes_info(node_name)
                info = nodes_info[0]
                api_node = APINode(info)
                self.__iadd__(api_node)     # add to current set
                return api_node
            def filter(self, **kwargs):
                """Returns the set of nodes matching the given attributes"""
                new_set = APINodesDict({})
                for node in d.values():
                    node_ok = True
                    for k, v in kwargs.items():
                        if getattr(node, k) != v:
                            node_ok = False
                            break
                    if node_ok:
                        new_set += node
                return new_set
            def __iadd__(self, node):
                if not isinstance(node, APINodeImplBase):
                    raise NotImplemented
                for existing_node in d.values():
                    if existing_node.name == node.name:
                        raise AlreadyInSetException(f"{node.name} already belongs to this set.")
                # update registry items to include the new node
                new_items = tuple(d.items()) + ((node.name, node),)
                new_d = create_names_dict(new_items, name_format = snakecase)
                d.update(new_d)
                return self
            def __add__(self, node):
                new_set = APINodesDict(d.copy())
                new_set += node     # call __iadd__() above
                return new_set
        return APINodesDictImpl()

def get_nodes():
    with silent_server_link() as server:
        nodes_info = server.get_nodes_info('all-nodes')
    d = create_names_dict(
        ((node_info['name'], APINode(node_info)) \
         for node_info in nodes_info),
        name_format = snakecase
    )
    return APINodesDict(d)
