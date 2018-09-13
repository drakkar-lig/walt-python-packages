import socket, random, subprocess, shlex, signal, os
from collections import defaultdict
from snimpy import snmp
from walt.common.tcp import Requests
from walt.common.tools import do, format_sentence_about_nodes, failsafe_makedirs
from walt.server.const import SSH_COMMAND, WALT_NODE_NET_SERVICE_PORT
from walt.server.threads.main.filesystem import Filesystem
from walt.server.threads.main.network.netsetup import NetSetup
from walt.server.threads.main.nodes.register import handle_registration_request
from walt.server.threads.main.nodes.show import show
from walt.server.threads.main.nodes.wait import WaitInfo
from walt.server.threads.main.nodes.expose import ExposeManager
from walt.server.threads.main.transfer import validate_cp
from walt.server.threads.main.network.tools import ip, get_walt_subnet, get_server_ip
from walt.server.tools import to_named_tuple

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

MSG_NOT_VIRTUAL = "WARNING: %s is not a virtual node. IGNORED.\n"

FS_CMD_PATTERN = SSH_COMMAND + ' root@%(node_ip)s "%%(prog)s %%(prog_args)s"'

CMD_START_VNODE = 'screen -S walt.node.%(name)s -d -m   \
       walt-fake-ipxe-node %(mac)s %(ip)s %(netmask)s "%(gateway)s" %(name)s %(server_ip)s'
CMD_ADD_SSH_KNOWN_HOST = "  mkdir -p /root/.ssh && ssh-keygen -F %(ip)s || \
                            ssh-keyscan -t ecdsa %(ip)s >> /root/.ssh/known_hosts"

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
    def __init__(self, tcp_server, ev_loop, db, devices, topology, **kwargs):
        self.db = db
        self.devices = devices
        self.topology = topology
        self.other_kwargs = kwargs
        self.wait_info = WaitInfo()
        self.expose_manager = ExposeManager(tcp_server, ev_loop)

    def prepare(self):
        # set booted flag of all nodes to False for now
        self.db.execute('UPDATE nodes SET booted = false;')
        # prepare the network setup for NAT support
        self.prepare_netsetup()

    def restore(self):
        # start virtual nodes
        for vnode in self.db.select('devices', type = 'node', virtual = True):
            node = self.devices.get_complete_device_info(vnode.mac)
            self.start_vnode(node)

    def prepare_netsetup(self):
        # force-create the chain WALT and assert it is empty
        do("iptables --new-chain WALT")
        do("iptables --flush WALT")
        do("iptables --append WALT --jump DROP")
        # allow traffic on the bridge (virtual <-> physical nodes)
        do("iptables --append FORWARD "
           "--in-interface walt-net --out-interface walt-net "
           "--jump ACCEPT")
        # allow connections back to WalT
        do("iptables --append FORWARD "
           "--out-interface walt-net --match state --state RELATED,ESTABLISHED "
           "--jump ACCEPT")
        # jump to WALT chain for other traffic
        do("iptables --append FORWARD "
           "--in-interface walt-net "
           "--jump WALT")
        # NAT nodes traffic that is allowed to go outside
        do("iptables --table nat --append POSTROUTING "
           "! --out-interface walt-net --source %s "
           "--jump MASQUERADE" % str(get_walt_subnet()))
        # Set the configuration of all NAT-ed nodes
        for node_ip in self.db.execute("""\
                SELECT ip FROM nodes
                INNER JOIN devices ON devices.mac = nodes.mac
                WHERE netsetup = %d;
                """ % NetSetup.NAT):
            do("iptables --insert WALT --source '%s' --jump ACCEPT" % node_ip)

    def try_kill_vnode(self, node_name):
        # note: kvm processes may already have ended because they are subprocesses
        # and they may have also received the signal that caused us to be there.
        do("screen -S walt.node.%(name)s -X quit" % dict(name = node_name))

    def cleanup(self):
        # stop virtual nodes
        for vnode in self.db.select('devices', type = 'node', virtual = True):
            self.try_kill_vnode(vnode.name)
        self.cleanup_netsetup()

    def cleanup_netsetup(self):
        # drop rules set by prepare_netsetup
        do("iptables --table nat --delete POSTROUTING "
           "! --out-interface walt-net --source %s "
           "--jump MASQUERADE" % str(get_walt_subnet()))
        do("iptables --delete FORWARD "
           "--in-interface walt-net "
           "--jump WALT")
        do("iptables --delete FORWARD "
           "--out-interface walt-net --match state --state RELATED,ESTABLISHED "
           "--jump ACCEPT")
        do("iptables --delete FORWARD "
           "--in-interface walt-net --out-interface walt-net "
           "--jump ACCEPT")
        do("iptables --flush WALT")
        do("iptables --delete-chain WALT")

    def forget_vnode(self, node_name):
        self.try_kill_vnode(node_name)

    def as_node_set(self, names):
        return ','.join(sorted(names))

    def register_node(self, mac, model):
        handle_registration_request(
                db = self.db,
                mac = mac,
                model = model,
                **self.other_kwargs
        )

    def connect(self, requester, node_name, hide_issues = False):
        nodes_ip = self.get_nodes_ip(
                        requester, node_name)
        if len(nodes_ip) == 0:
            return None # error was already reported
        link = ServerToNodeLink(nodes_ip[0])
        connect_status = link.connect()
        if not connect_status[0]:
            if not hide_issues:
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
        free_ips.pop(0)     # first IP is for WalT server
        for item in self.db.execute(\
                'SELECT ip FROM devices WHERE ip IS NOT NULL').fetchall():
            device_ip = ip(item.ip)
            if device_ip in subnet and device_ip in free_ips:
                free_ips.remove(device_ip)
        free_ip = str(free_ips[0])
        return free_mac, free_ip, 'pc-x86-64'

    def start_vnode(self, node):
        if not os.path.exists('/etc/qemu/bridge.conf'):
            failsafe_makedirs('/etc/qemu')
            with open('/etc/qemu/bridge.conf', 'w') as f:
                f.write('allow walt-net\n')
        server_ip = get_server_ip()
        netmask = str(get_walt_subnet().netmask)
        gateway = server_ip if node.netsetup == NetSetup.NAT else ''
        cmd = CMD_START_VNODE % dict(
            mac = node.mac,
            ip = node.ip,
            netmask = netmask,
            gateway = gateway,
            name = node.name,
            server_ip = server_ip
        )
        subprocess.Popen(shlex.split(cmd))

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

    def get_virtual_node_info(self, requester, node_name):
        node = self.get_node_info(requester, node_name)
        if node is None:
            return None     # error already reported
        if not node.virtual:
            requester.stderr.write(\
                'FAILED: %s is a real node (not virtual).\n' % node_name)
            return None
        return node

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

    def get_nodes_using_image(self, image_fullname):
        nodes = self.db.select('nodes', image = image_fullname)
        return tuple(
                self.devices.get_complete_device_info(n.mac)
                for n in nodes)

    def prepare_ssh_access_for_ip(self, ip):
        cmd = CMD_ADD_SSH_KNOWN_HOST % dict(ip = ip)
        do(cmd)

    def prepare_ssh_access(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return
        for node in nodes:
            self.prepare_ssh_access_for_ip(node.ip)

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
            return self.as_node_set(n.name for n in nodes_really_ok)
        else:
            return None

    def softreboot(self, requester, node_set, hide_issues):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None # error already reported
        # first, we pass the 'booted' flag of all nodes to false
        # (if we manage to reboot them, they will be unreachable
        #  for a little time; if we do not manage to reboot them,
        #  this probably means they are down, thus not booted...)
        for node in nodes:
            self.db.update('nodes', 'mac', mac = node.mac, booted = False);
        self.db.commit()
        nodes_ko, nodes_ok = [], []
        for node in nodes:
            link = self.connect(requester, node.name, hide_issues)
            if link == None:
                nodes_ko.append(node.name)
                continue
            res = link.request('REBOOT')
            del link
            if not res[0]:
                if not hide_issues:
                    requester.stderr.write('Soft-reboot request to %s failed: %s\n' % \
                        (node.name, res[1]))
                nodes_ko.append(node.name)
                continue
            nodes_ok.append(node.name)
        if len(nodes_ok) > 0:
            requester.stdout.write(format_sentence_about_nodes(
                '%s was(were) rebooted.' , nodes_ok) + '\n')
        # return nodes OK and KO in node_set form
        return self.as_node_set(nodes_ok), self.as_node_set(nodes_ko)

    def virtual_or_physical(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None # error already reported
        vnodes, pnodes = [], []
        for node in nodes:
            if node.virtual:
                vnodes.append(node.name)
            else:
                pnodes.append(node.name)
        # return the 2 sets in node_set form
        return self.as_node_set(vnodes), self.as_node_set(pnodes)

    def hard_reboot_vnodes(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None # error already reported
        nodes_ok = []
        for node in nodes:
            if not node.virtual:
                requester.stderr.write(MSG_NOT_VIRTUAL % node.name)
                continue
            # terminate VM by quitting screen session
            self.try_kill_vnode(node.name)
            # restart VM
            self.start_vnode(node)
            nodes_ok.append(node.name)
        if len(nodes_ok) > 0:
            requester.stdout.write(format_sentence_about_nodes(
                '%s was(were) rebooted.' , nodes_ok) + '\n')

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
        # update booted flag in db
        self.db.update('nodes', 'mac', mac=node_info.mac, booted=True)
        self.db.commit()
        # unblock any related "walt node wait" command.
        self.wait_info.node_bootup_event(node_info)

    def develop_node_set(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None
        return self.as_node_set(n.name for n in nodes)

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
        return self.get_node_info(requester, node_name) != None

    def get_cp_entity_filesystem(self, requester, node_name):
        node_ip = self.get_node_ip(requester, node_name)
        self.prepare_ssh_access_for_ip(node_ip)
        return Filesystem(FS_CMD_PATTERN % dict(node_ip = node_ip))

    def get_cp_entity_attrs(self, requester, node_name):
        owned = not self.includes_nodes_not_owned(requester, node_name, True)
        ip = self.get_node_ip(requester, node_name)
        return dict(node_name = node_name,
                    node_ip = ip,
                    node_owned = owned)

    def netsetup_configure(self, requester, node_set, netsetup_value):
        new_netsetup_state = NetSetup(netsetup_value)
        for node_info in self.parse_node_set(requester, node_set):
            if node_info.netsetup == new_netsetup_state:
                # skip this node: already configured
                continue
            # Update the database
            self.db.update("nodes", "mac", mac=node_info.mac, netsetup=new_netsetup_state)
            # Update iptables
            do("iptables %(action)s WALT --source '%(ip)s' --jump ACCEPT" %
               dict(ip=node_info.ip,
                    action="--insert" if new_netsetup_state == NetSetup.NAT else "--delete"))
            # Validate the modifications
            self.db.commit()
