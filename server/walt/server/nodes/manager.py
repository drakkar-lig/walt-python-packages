from walt.common.tcp import Requests
from walt.server.nodes.register import NodeRegistrationHandler
from walt.server.tools import format_paragraph, format_sentence_about_nodes, \
                                merge_named_tuples
from walt.common.nodetypes import is_a_node_type_name
from walt.server.transfer import validate_cp
from walt.server.filesystem import Filesystem
from walt.server.const import SSH_COMMAND

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
You are currently using no nodes. (tip: walt --help-about node-terminology)"""

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

NODE_SET_QUERIES = {
        'my-nodes': """
            SELECT  d.name as name
            FROM devices d, nodes n
            WHERE   d.mac = n.mac
            AND     split_part(n.image, '/', 1) = '%s'
            ORDER BY name;""",
        'all-nodes': """
            SELECT  d.name as name
            FROM devices d, nodes n
            WHERE   d.mac = n.mac
            ORDER BY name;"""
}

MSG_NODE_NEVER_REGISTERED = """\
Node %s was eventually detected but never registered itself to the server.
It seems it is not running a valid WalT boot image.
"""

FS_CMD_PATTERN = SSH_COMMAND + ' root@%(node_ip)s %%(prog)s %%(prog_args)s'

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
        device_info = self.devices.get_device_info(requester, node_name)
        if device_info == None:
            return None # error already reported
        device_type = device_info.type
        if not is_a_node_type_name(device_type):
            requester.stderr.write('%s is not a node, it is a %s.\n' % \
                                    (node_name, device_type))
            return None
        node_info = self.db.select_unique("nodes", mac=device_info.mac)
        if node_info == None:
            requester.stderr.write(MSG_NODE_NEVER_REGISTERED % node_name)
            return None
        return merge_named_tuples(device_info, node_info)

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

    def filter_on_connectivity(self, requester, nodes, warn):
        nodes_ok = []
        nodes_ko = []
        for node in nodes:
            sw_ip, sw_port = self.devices.topology.get_connectivity_info( \
                                    node.mac)
            if sw_ip:
                nodes_ok.append(node)
            else:
                nodes_ko.append(node)
        if len(nodes_ko) > 0 and warn:
            requester.stderr.write(format_sentence_about_nodes(
                '%s currently cannot be reached.',
                [n.name for n in nodes_ko]) + '\n')
        return nodes_ok, nodes_ko

    def setpower(self, requester, node_set, poweron, warn_unreachable):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None # error already reported
        # verify connectivity of all designated nodes
        nodes_ok, nodes_ko = self.filter_on_connectivity( \
                            requester, nodes, warn_unreachable)
        if len(nodes_ok) == 0:
            return False
        # otherwise, at least one node can be reached, so do it.
        for node in nodes_ok:
            self.devices.topology.setpower(node.mac, poweron)
        s_poweron = {True:'on',False:'off'}[poweron]
        requester.stdout.write(format_sentence_about_nodes(
            '%s was(were) powered ' + s_poweron + '.' ,
            [n.name for n in nodes_ok]) + '\n')
        return True

    def parse_node_set(self, requester, node_set):
        sql = None
        if node_set == None or node_set == 'my-nodes':
            sql = NODE_SET_QUERIES['my-nodes'] % requester.username
        elif node_set == 'all-nodes':
            sql = NODE_SET_QUERIES['all-nodes']
        if sql:
            nodes = [record[0] for record in self.db.execute(sql) ]
        else:
            # otherwise the list is explicit
            nodes = node_set.split(',')
        nodes = [self.get_node_info(requester, n) for n in nodes]
        if None in nodes:
            return None
        if len(nodes) == 0:
            requester.stderr.write('No matching nodes found! (tip: walt --help-about node-terminology)\n')
            return None
        return sorted(nodes)

    def includes_nodes_not_owned(self, requester, node_set, warn):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None
        not_owned = [ n for n in nodes \
                if not n.image.startswith(requester.username + '/') ]
        if len(not_owned) == 0:
            return False
        else:
            if warn:
                requester.stderr.write(format_sentence_about_nodes(
                    'Warning: %s seems(seem) to be used by another(other) user(users).',
                    [n.name for n in not_owned]) + '\n')
            return True

    def validate_cp(self, requester, src, dst):
        return validate_cp("node", self, requester, src, dst)

    def validate_cp_entity(self, requester, node_name):
        return self.get_reachable_node_ip(requester, node_name) != None

    def get_cp_entity_filesystem(self, requester, node_name):
        node_ip = self.get_node_ip(requester, node_name)
        return Filesystem(FS_CMD_PATTERN % dict(node_ip = node_ip))

    def get_cp_entity_attrs(self, requester, node_name):
        return dict(node_ip = self.get_node_ip(requester, node_name))
