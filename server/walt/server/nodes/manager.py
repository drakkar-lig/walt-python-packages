from walt.common.tcp import Requests
from walt.server.nodes.register import NodeRegistrationHandler
from walt.server.tools import format_paragraph
from walt.common.nodetypes import is_a_node_type_name

# the split_part() expression below allows to show only
# the image tag to the user (instead of the full docker name).
USER_NODES_QUERY = """
    SELECT  d.name as name, d.type as type,
            split_part(n.image, ':', 2) as image,
            d.ip as ip,
            (case when d.reachable = 1 then 'yes' else 'NO' end) as reachable
    FROM devices d, nodes n
    WHERE   d.mac = n.mac
    AND     split_part(n.image, '/', 1) = '%s'
    ORDER BY name;"""

OTHER_NODES_QUERY = """
    SELECT  d.name as name, d.type as type,
            split_part(n.image, '/', 1) as image_owner,
            'server:' ||
            split_part(n.image, '/', 1) ||
            '/' ||
            split_part(n.image, ':', 2) as clonable_image_link,
            d.ip as ip,
            (case when d.reachable = 1 then 'yes' else 'NO' end) as reachable
    FROM devices d, nodes n
    WHERE   d.mac = n.mac
    AND     split_part(n.image, '/', 1) != '%s'
    ORDER BY image_owner, name;"""

MSG_USING_NO_NODES = """\
You are currently using no nodes."""

MSG_RERUN_WITH_ALL = """\
Re-run with --all to see all deployable nodes."""

TITLE_NODE_SHOW_USER_NODES_PART = """\
Nodes with an image that you own:"""

TITLE_NODE_SHOW_OTHER_NODES_PART = """\
The following nodes are likely to be used by other users, since you do
not own the image deployed on them."""

MSG_NO_NODES = """\
No nodes detected!"""

MSG_NO_OTHER_NODES = """\
No other nodes were detected (apart from the ones listed above)."""

class NodesManager(object):
    def __init__(self, db, tcp_server, devices, **kwargs):
        self.db = db
        self.current_register_requests = set()
        self.devices = devices
        self.kwargs = kwargs
        tcp_server.register_listener_class(
                    req_id = Requests.REQ_REGISTER_NODE,
                    cls = NodeRegistrationHandler,
                    current_requests = self.current_register_requests,
                    db = self.db,
                    devices = self.devices,
                    **self.kwargs)

    def show(self, requester, show_all):
        result_msg = ''
        user_nodes_query = USER_NODES_QUERY % requester.username
        res_user = self.db.execute(user_nodes_query).fetchall()
        if len(res_user) == 0 and not show_all:
            return MSG_USING_NO_NODES + '\n' + MSG_RERUN_WITH_ALL
        if len(res_user) > 0:
            footnote = None
            if not show_all:
                footnote = MSG_RERUN_WITH_ALL
            result_msg += format_paragraph(
                            TITLE_NODE_SHOW_USER_NODES_PART,
                            self.db.pretty_printed_resultset(res_user),
                            footnote)
        if not show_all:
            return result_msg
        # show free nodes (i.e. nodes with images owned by 'waltplatform')
        other_nodes_query = OTHER_NODES_QUERY % requester.username
        res_other = self.db.execute(other_nodes_query).fetchall()
        if len(res_other) == 0 and len(res_user) == 0:
            return MSG_NO_NODES + '\n'
        if len(res_other) == 0:
            result_msg += MSG_NO_OTHER_NODES + '\n'
        else:
            result_msg += format_paragraph(
                            TITLE_NODE_SHOW_OTHER_NODES_PART,
                            self.db.pretty_printed_resultset(res_other))
        return result_msg

    def get_node_info(self, requester, node_name):
        node_info = self.devices.get_device_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        device_type = node_info.type
        if not is_a_node_type_name(device_type):
            requester.stderr.write('%s is not a node, it is a %s.\n' % \
                                    (node_name, device_type))
            return None
        return node_info

    def get_reachable_node_info(self, requester, node_name, after_rescan = False):
        node_info = self.get_node_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        if node_info.reachable == 0:
            if after_rescan:
                requester.stderr.write(
                        'Connot reach %s. The node seems dead or disconnected.\n' % \
                                    node_name)
                return None
            else:
                # rescan, just in case, and retry
                self.devices.topology.rescan()   # just in case
                return self.get_reachable_node_info(
                        requester, node_name, after_rescan = True)
        return node_info

    def get_node_ip(self, requester, node_name):
        node_info = self.get_node_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        if node_info.ip == None:
            self.notify_unknown_ip(requester, node_name)
        return node_info.ip

    def get_reachable_node_ip(self, requester, node_name):
        node_info = self.get_reachable_node_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        return node_info.ip

    def setpower(self, requester, node_name, poweron):
        node_info = self.get_node_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        return self.devices.topology.setpower(node_info.mac, poweron)

