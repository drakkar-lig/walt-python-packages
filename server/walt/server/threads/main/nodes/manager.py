import socket, random
from collections import defaultdict
from snimpy import snmp
from walt.common.tcp import Requests
from walt.common.tools import format_sentence_about_nodes
from walt.server.const import SSH_COMMAND, WALT_NODE_NET_SERVICE_PORT
from walt.server.threads.main.filesystem import Filesystem
from walt.server.threads.main.nodes.register import handle_registration_request
from walt.server.threads.main.nodes.show import show
from walt.server.threads.main.nodes.wait import WaitInfo
from walt.server.threads.main.transfer import validate_cp
from walt.server.threads.main.network.tools import ip, get_walt_subnet
from walt.server.tools import merge_named_tuples

NODE_CONNECTION_TIMEOUT = 1

NODE_SET_QUERIES = {
        'my-nodes': """
            SELECT  d.name as name
            FROM devices d, nodes n, images i
            WHERE   d.mac = n.mac
            AND     n.image = i.fullname
            AND     i.ready = True
            AND     split_part(n.image, '/', 1) = '%s'
            ORDER BY name;""",
        'all-nodes': """
            SELECT  d.name as name
            FROM devices d, nodes n, images i
            WHERE   d.mac = n.mac
            AND     n.image = i.fullname
            AND     i.ready = True
            ORDER BY name;"""
}

MSG_CONNECTIVITY_UNKNOWN = """\
%s: Unknown PoE switch port. Cannot proceed! Try 'walt device rescan'.
"""

MSG_POE_REBOOT_UNABLE_EXPLAIN = """\
%%s is(are) connected on switch '%(sw_name)s' which has PoE disabled. Cannot proceed!
If '%(sw_name)s' is PoE-capable, you can activate PoE hard-reboots by running:
$ walt device admin %(sw_name)s
"""

MSG_POE_REBOOT_FAILED = """\
FAILED to turn node %(node_name)s %(state)s using PoE: SNMP request to %(sw_name)s (%(sw_ip)s) failed.
"""

FS_CMD_PATTERN = SSH_COMMAND + ' root@%(node_ip)s %%(prog)s %%(prog_args)s'

class ServerToNodeLink:
    def __init__(self, ip_address):
        self.node_ip = ip_address
        self.conn = None
        self.rfile = None

    def connect(self):
        try:
            self.conn = socket.create_connection(
                    (self.node_ip, WALT_NODE_NET_SERVICE_PORT),
                    NODE_CONNECTION_TIMEOUT)
            self.rfile = self.conn.makefile()
        except socket.timeout:
            return (False, 'Connection timeout.')
        except socket.error:
            return (False, 'Connection failed.')
        return (True,)

    def request(self, req):
        try:
            self.conn.send(req + '\n')
            resp = self.rfile.readline().split(' ',1)
            resp = tuple(part.strip() for part in resp)
            if resp[0] == 'OK':
                return (True,)
            elif len(resp) == 2:
                return (False, resp[1])
            else:
                return (False, 'Node did not acknowledge reboot request.')
        except socket.timeout:
            return (False, 'Connection timeout.')
        except socket.error:
            return (False, 'Connection failed.')

    def __del__(self):
        if self.conn:
            self.rfile.close()
            self.conn.close()

class NodesManager(object):
    def __init__(self, db, devices, topology, **kwargs):
        self.db = db
        self.devices = devices
        self.topology = topology
        self.other_kwargs = kwargs
        self.wait_info = WaitInfo()

    def register_node(self, mac, model):
        handle_registration_request(
                db = self.db,
                mac = mac,
                model = model,
                **self.other_kwargs
        )

    def connect(self, requester, node_name):
        nodes_ip = self.get_nodes_ip(
                        requester, node_name)
        if len(nodes_ip) == 0:
            return None # error was already reported
        link = ServerToNodeLink(nodes_ip[0])
        connect_status = link.connect()
        if not connect_status[0]:
            requester.stderr.write('Error connecting to %s: %s\n' % \
                    (node_name, connect_status[1]))
            return None
        return link

    def blink(self, requester, node_name, blink_status):
        link = self.connect(requester, node_name)
        if link == None:
            return False # error was already reported
        res = link.request('BLINK %d' % int(blink_status))
        del link
        if not res[0]:
            requester.stderr.write('Blink request to %s failed: %s\n' % \
                    (node_name, res[1]))
            return False
        return True

    def show(self, requester, show_all):
        return show(self.db, requester, show_all)

    def generate_vnode_info(self):
        # random mac address generation
        while True:
            free_mac = "52:54:00:%02x:%02x:%02x" % (
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255),
            )
            if self.db.select_unique('devices', mac = free_mac) is None:
                break   # ok, mac is free
        # find a free ip
        subnet = get_walt_subnet()
        free_ips = list(subnet.hosts())
        for item in self.db.execute(\
                'SELECT ip FROM devices WHERE ip IS NOT NULL').fetchall():
            device_ip = ip(item.ip)
            if device_ip in subnet:
                free_ips.remove(device_ip)
        free_ip = str(free_ips[0])
        return free_mac, free_ip, 'pc-x86-64'

    def get_node_info(self, requester, node_name):
        device_info = self.devices.get_device_info(requester, node_name)
        if device_info == None:
            return None # error already reported
        device_type = device_info.type
        if device_type != 'node':
            requester.stderr.write('%s is not a node, it is a %s.\n' % \
                                    (node_name, device_type))
            return None
        return self.devices.get_complete_device_info(device_info.mac)

    def get_reachable_node_info(self, requester, node_name):
        node_info = self.get_node_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        if node_info.reachable == 0:
            link = ServerToNodeLink(node_info.ip)
            res = link.connect()
            del link
            if not res[0]:
                requester.stderr.write(
                        'Connot reach %s. The node seems dead or disconnected.\n' % \
                                    node_name)
                return None
            else:
                # Could connect. Node should be marked as reachable.
                self.db.update('devices', 'mac', mac=node_info.mac, reachable=1)
                node_info = self.get_node_info(requester, node_name)
        return node_info

    def get_node_ip(self, requester, node_name):
        node_info = self.get_node_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        if node_info.ip == None:
            self.notify_unknown_ip(requester, node_name)
        return node_info.ip

    def get_nodes_ip(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return () # error already reported
        return tuple(node.ip for node in nodes)

    def filter_poe_rebootable(self, requester, nodes,
                warn_unknown_connectivity, warn_poe_forbidden):
        nodes_ok = []
        nodes_unknown = []
        nodes_forbidden = defaultdict(list)
        for node in nodes:
            sw_info, sw_port = self.topology.get_connectivity_info( \
                                    node.mac)
            if sw_info:
                if sw_info.poe_reboot_nodes == True:
                    nodes_ok.append(node)
                else:
                    nodes_forbidden[sw_info.name].append(node)
            else:
                nodes_unknown.append(node)
        if len(nodes_unknown) > 0 and warn_unknown_connectivity:
            requester.stderr.write(format_sentence_about_nodes(
                MSG_CONNECTIVITY_UNKNOWN, [n.name for n in nodes_unknown]))
        if len(nodes_forbidden) > 0 and warn_poe_forbidden:
            for sw_name, sw_nodes in nodes_forbidden.items():
                explain = MSG_POE_REBOOT_UNABLE_EXPLAIN % dict(
                    sw_name = sw_name
                )
                requester.stderr.write(format_sentence_about_nodes(
                    explain,
                    [n.name for n in sw_nodes]))
        return nodes_ok, nodes_unknown, nodes_forbidden

    def setpower(self, requester, node_set, poweron, warn_poe_issues):
        """Hard-reboot nodes by setting the PoE switch port off and back on"""
        # we have to verify that:
        # - we know where each node is connected (PoE switch port)
        # - PoE remote control is allowed on this switch
        #
        # we verify this in several steps:
        # 1- we call filter_poe_rebootable() but disabling
        #    warnings about nodes with unknown connectivity
        # 2- if such nodes were returned, we rescan the network,
        #    and then call filter_poe_rebootable() again,
        #    for those problematic nodes only, and this time
        #    with the warning enabled.
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None # error already reported
        nodes_ok, nodes_unknown, nodes_forbidden = \
                    self.filter_poe_rebootable( \
                                requester, nodes,
                                False,
                                warn_poe_issues)
        if len(nodes_unknown) > 0:
            # rescan and retry
            self.topology.rescan()
            nodes_ok2, nodes_unknown2, nodes_forbidden2 = \
            self.filter_poe_rebootable( requester,
                                        nodes_unknown,
                                        warn_poe_issues,
                                        warn_poe_issues)
            nodes_ok += nodes_ok2
        if len(nodes_ok) == 0:
            return None
        # otherwise, at least one node can be reached, so do it.
        s_state = {True:'on',False:'off'}[poweron]
        nodes_really_ok = []
        for node in nodes_ok:
            try:
                self.topology.setpower(node.mac, poweron)
                nodes_really_ok.append(node)
            except snmp.SNMPException:
                sw_info, sw_port = \
                    self.topology.get_connectivity_info(node.mac)
                requester.stderr.write(MSG_POE_REBOOT_FAILED % dict(
                        node_name = node.name,
                        state = s_state,
                        sw_name = sw_info.name,
                        sw_ip = sw_info.ip))
        if len(nodes_really_ok) > 0:
            requester.stdout.write(format_sentence_about_nodes(
                '%s was(were) powered ' + s_state + '.' ,
                [n.name for n in nodes_really_ok]) + '\n')
            # return successful nodes as a node_set
            return ','.join(n.name for n in nodes_really_ok)
        else:
            return None

    def softreboot(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None # error already reported
        # first, we pass all nodes to unreachable
        # (if we manage to reboot them, they will be unreachable
        #  for a little time; if we do not manage to reboot them,
        #  this means there are already unreachable...)
        for node in nodes:
            self.db.update('devices', 'mac', mac = node.mac, reachable = 0);
        self.db.commit()
        nodes_ko, nodes_ok = [], []
        for node in nodes:
            link = self.connect(requester, node.name)
            if link == None:
                nodes_ko.append(node.name)
                continue
            res = link.request('REBOOT')
            del link
            if not res[0]:
                requester.stderr.write('Soft-reboot request to %s failed: %s\n' % \
                        (node.name, res[1]))
                nodes_ko.append(node.name)
                continue
            nodes_ok.append(node.name)
        if len(nodes_ok) > 0:
            requester.stdout.write(format_sentence_about_nodes(
                '%s was(were) rebooted.' , nodes_ok) + '\n')
        # return nodes OK and KO in node_set form
        return ','.join(sorted(nodes_ok)), ','.join(sorted(nodes_ko))

    def parse_node_set(self, requester, node_set):
        username = requester.get_username()
        if not username:
            return ()    # client already disconnected, give up
        sql = None
        if node_set == None or node_set == 'my-nodes':
            sql = NODE_SET_QUERIES['my-nodes'] % username
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

    def wait(self, requester, task, node_set):
        nodes = self.parse_node_set(requester, node_set)
        self.wait_info.wait(requester, task, nodes)

    def node_bootup_event(self, node_name):
        node_info = self.get_node_info(None, node_name)
        self.wait_info.node_bootup_event(node_info)

    def develop_node_set(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None
        return ','.join(n.name for n in nodes)

    def includes_nodes_not_owned(self, requester, node_set, warn):
        username = requester.get_username()
        if not username:
            return False    # client already disconnected, give up
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None
        not_owned = [ n for n in nodes \
                if not (n.image.startswith(username + '/') or
                        n.image.startswith('waltplatform/')) ]
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
        return self.get_reachable_node_info(requester, node_name) != None

    def get_cp_entity_filesystem(self, requester, node_name):
        node_ip = self.get_node_ip(requester, node_name)
        return Filesystem(FS_CMD_PATTERN % dict(node_ip = node_ip))

    def get_cp_entity_attrs(self, requester, node_name):
        return dict(node_ip = self.get_node_ip(requester, node_name))
