#!/usr/bin/env python

import sys, json, re, time
from dateutil.relativedelta import relativedelta
from snimpy.snmp import SNMPException

from walt.common.tools import get_mac_address, format_sentence
from walt.server import const
from walt.server.threads.main import snmp
from walt.server.threads.main.snmp import NoSNMPVariantFound
from walt.server.threads.main.devices.grouper import Grouper
from walt.server.threads.main.network.tools import \
        ip_in_walt_network, ip_in_walt_adm_network, lldp_update, get_server_ip
from walt.server.threads.main.tree import Tree

NOTE_EXPLAIN_UNREACHABLE = "devices marked with parentheses were not detected at last scan"
NOTE_EXPLAIN_UNKNOWN = "type of devices marked with <? ... ?> is unknown"

TIP_ADD_FLAG_ALL = "use 'walt device tree --all' to see all devices detected"
TIP_DEVICE_SHOW = "use 'walt device show' for device details"
TIP_DEVICE_RESCAN = "use 'walt device rescan' to update"
TIP_DEVICE_ADMIN_1 = "use 'walt device config <device> type=switch' to let WalT know a given device is a switch"
TIP_DEVICE_ADMIN_2 = "use 'walt device config ...' (see walt help show device-config) to let WalT explore forbidden switches"
TIPS_MIN = (TIP_DEVICE_SHOW, TIP_DEVICE_ADMIN_2, TIP_DEVICE_RESCAN)

NOTE_LAST_NETWORK_SCAN = "\
this view comes from last network scan, issued %s ago (use 'walt device rescan' to update)"

NOTE_LAST_NETWORK_SCAN_UNKNOWN = "\
this view comes from last network scan (use 'walt device rescan' to update)"

MSG_NO_NEIGHBORS = """\
WalT Server did not detect any neighbor!
"""
MSG_UNKNOWN_TOPOLOGY = """\
Sorry, topology is unknown. Ensure a switch is connected to server (on walt-net interface) and run "walt device rescan".
"""

def format_explanation(item_type, items):
    if len(items) == 0:
        return ''
    if len(items) == 1:
        return item_type + ': ' + items[0] + '.\n'
    return item_type + 's:' + ''.join('\n- ' + item for item in items) + '\n'

attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']
def human_readable_delay(seconds):
    if seconds < 1:
        seconds = 1
    delta = relativedelta(seconds=seconds)
    items = []
    for attr in attrs:
        attr_val = getattr(delta, attr)
        if attr_val == 0:
            continue
        plur_or_sing_attr = attr if attr_val > 1 else attr[:-1]
        items.append('%d %s' % (attr_val, plur_or_sing_attr))
    # keep only 2 items max, this is enough granularity for a human.
    items = items[:2]
    return ' and '.join(items)

class Topology(object):
    def __init__(self):
        # links as a dict (mac1, mac2) -> (port1, port2, confirmed)
        self.links = {}

    def is_empty(self):
        return len(self.links) == 0

    def register_neighbor(self, local_mac, local_port, neighbor_mac):
        mac1, mac2 = sorted((local_mac, neighbor_mac))
        link = self.links.get((mac1, mac2))
        if link == None:
            # first time we see this link
            if local_mac < neighbor_mac:
                port1, port2 = local_port, None
            else:
                port1, port2 = None, local_port
            self.links[(mac1, mac2)] = port1, port2, True
        else:
            # update port on existing link
            if local_mac < neighbor_mac:
                self.links[(mac1, mac2)] = local_port, link[1], link[2]
            else:
                self.links[(mac1, mac2)] = link[0], local_port, link[2]

    def load_from_db(self, db):
        for db_link in db.select('topology'):
            self.links[(db_link.mac1, db_link.mac2)] = \
                       (db_link.port1, db_link.port2, db_link.confirmed)

    def save_to_db(self, db):
        db.delete('topology');
        for link_macs, link_info in self.links.items():
            db.insert('topology',   mac1 = link_macs[0],
                                    mac2 = link_macs[1],
                                    port1 = link_info[0],
                                    port2 = link_info[1],
                                    confirmed = link_info[2])
        db.commit()

    def unconfirm(self, devices):
        new_links = {}
        # any device connected to one of the specified
        # switches or server should now have its 'confirmed' flag
        # set to false.
        device_macs = set(dev.mac for dev in devices)
        for k in self.links:
            mac1, mac2 = k
            port1, port2, confirmed = self.links[k]
            if mac1 in device_macs or mac2 in device_macs:
                confirmed = False
            new_links[k] = port1, port2, confirmed
        self.links = new_links

    def __iter__(self):
        # iterate over links info
        for macs, info in self.links.items():
            yield macs + info   # concatenate the tuples

    def merge_links_info(self, confirmed, unconfirmed):
        if confirmed[0] is None:
            port1 = unconfirmed[0]
        else:
            port1 = confirmed[0]
        if confirmed[1] is None:
            port2 = unconfirmed[1]
        else:
            port2 = confirmed[1]
        return port1, port2, True

    def merge_other(self, other):
        # build the union of 'self.links' and 'other.links';
        # in case of conflict, merge information.
        new_links = {}
        keys_self = set(self.links)
        keys_other = set(other.links)
        common_keys = keys_self & keys_other
        for k in common_keys:
            if self.links[k][2] < other.links[k][2]:
                confirmed, unconfirmed = other.links[k], self.links[k]
            else:
                confirmed, unconfirmed = self.links[k], other.links[k]
            new_links[k] = self.merge_links_info(confirmed, unconfirmed)
        for k in keys_self - keys_other:
            new_links[k] = self.links[k]
        for k in keys_other - keys_self:
            new_links[k] = other.links[k]
        # check if we have several links at the same location
        # (mac, non-null-port), and in this case keep the one confirmed.
        locations = {}
        for macs, info in new_links.copy().items():
            mac1, mac2, port1, port2, confirmed = macs + info
            if port1 is not None:
                conflicting_mac2 = locations.get((mac1, port1))
                if conflicting_mac2 is not None:
                    if confirmed: # this one is confirmed, discard the old one
                        new_links.pop((mac1, conflicting_mac2), None)
                        locations[(mac1, port1)] = mac2
                    else:         # this one is not confirmed, discard it
                        new_links.pop((mac1, mac2), None)
                else:
                    locations[(mac1, port1)] = mac2
            if port2 is not None:
                conflicting_mac1 = locations.get((mac2, port2))
                if conflicting_mac1 is not None:
                    if confirmed: # this one is confirmed, discard the old one
                        new_links.pop((conflicting_mac1, mac2), None)
                        locations[(mac2, port2)] = mac1
                    else:         # this one is not confirmed, discard it
                        new_links.pop((mac1, mac2), None)
                else:
                    locations[(mac2, port2)] = mac1
        self.links = new_links

    def cleanup(self, nodes_mac):
        # This procedure will remove obsolete links from moved devices,
        # and ensure we have no loops.
        # As a first criterion, we consider that nodes cannot have more
        # than 1 neighbor in the topology.
        found_nodes = {}
        for macs, info in self.links.copy().items():
            mac1, mac2, port1, port2, confirmed = macs + info
            is_node = (mac1 in nodes_mac), (mac2 in nodes_mac)
            if is_node[0] and is_node[1]:  # 1 and 2 are nodes ??
                # strange, should not have a link between two nodes
                self.links.remove((mac1, mac2))
                continue
            if is_node[0]:   # dev 1 is a node
                if mac1 in found_nodes:
                    # node 1 cannot be connected at 2 different places
                    if confirmed:
                        prev_mac2 = found_nodes[mac1]
                        self.links.remove(tuple(sorted((mac1, prev_mac2))))
                    else:
                        self.links.remove((mac1, mac2))
                else:
                    found_nodes[mac1] = mac2
                continue
            if is_node[1]:   # dev 2 is a node
                if mac2 in found_nodes:
                    # node 2 cannot be connected at 2 different places
                    if confirmed:
                        prev_mac1 = found_nodes[mac2]
                        self.links.remove(tuple(sorted((prev_mac1, mac2))))
                    else:
                        self.links.remove((mac1, mac2))
                else:
                    found_nodes[mac2] = mac1
                continue
        # The following will clear any remaining conflicts and ensure we
        # have no loops.
        # 1)  we initialize a set of 'accepted' connected groups of nodes,
        #     using the links that were detected during last
        #     scan, and record the set of unconfirmed links.
        # 2a) we drop unconfirmed links between 2 nodes already in the
        #     same connectivity group (otherwise it would create a loop).
        # 2b) we accept links between 2 nodes in different connectivity
        #     groups, and merge such a pair of connectivity groups into one.
        # 3)  we accept links between an accepted node (belonging
        #     to an accepted connectivity group) and a node not yet accepted.
        #     This newly accepted node is inserted into the connectity group.
        # 4)  As soon as the set of connectivity groups evolves (i.e. 2b or 3)
        #     we loop again from step 2.
        # --
        # this is step 1
        accepted_groups = Grouper()
        remaining_links = set()
        for mac1, mac2, port1, port2, confirmed in self:
            if confirmed:
                accepted_groups.group_items(mac1, mac2)
            else:
                remaining_links.add((mac1, mac2))
        while True:
            # this is step 2
            still_moving = False
            for mac1, mac2 in remaining_links.copy():
                if mac1 in accepted_groups and mac2 in accepted_groups:
                    # we will process this link
                    remaining_links.remove((mac1, mac2))
                    if accepted_groups.is_same_group(mac1, mac2):
                        self.links.pop((mac1, mac2))                # 2a: discard
                    else:
                        accepted_groups.group_items(mac1, mac2)     # 2b: accept
                        still_moving = True
                        break
            if still_moving:
                continue
            # this is step 3
            still_moving = False
            for mac1, mac2 in remaining_links.copy():
                # since we passed step 2, the following condition is
                # implicitely an exclusive or
                if mac1 in accepted_groups or mac2 in accepted_groups:
                    # we will process this link
                    remaining_links.remove((mac1, mac2))
                    accepted_groups.group_items(mac1, mac2)         # accept
                    still_moving = True
                    break
            if still_moving:
                continue
            break

    def get_neighbors(self, mac):
        for mac1, mac2 in self.links:
            if mac in (mac1, mac2):
                port1, port2, confirmed = self.links[(mac1, mac2)]
            if mac1 == mac:
                yield port1, mac2, port2, confirmed
            if mac2 == mac:
                yield port2, mac1, port1, confirmed

    def printed_tree(self, last_scan, stdout_encoding, root_mac, device_labels,
                        device_types, lldp_forbidden, show_all):
        t = Tree(stdout_encoding)
        # compute confirmed / unconfirmed nodes
        confirmed_macs = set()
        all_macs = set()
        for mac1, mac2, port1, port2, confirmed in self:
            all_macs.add(mac1)
            all_macs.add(mac2)
            if confirmed:
                confirmed_macs.add(mac1)
                confirmed_macs.add(mac2)
        # declare nodes
        for mac in all_macs:
            label = device_labels[mac]
            if device_types[mac] == 'switch':
                label = '-- %s --' % label
            elif device_types[mac] == 'unknown':
                label = '<? %s ?>' % label
            if mac not in confirmed_macs:
                label = '(%s)' % label
            t.add_node(mac, label)
        # declare children
        for mac1, mac2, port1, port2, confirmed in self:
            for node_mac, parent_mac, parent_port in \
                    ((mac1, mac2, port2), (mac2, mac1, port1)):
                if device_types[parent_mac] == 'switch':
                    if show_all or device_types[node_mac] != 'unknown':
                        t.add_child(parent_mac, parent_port, node_mac)
        # prune parts of the tree
        self.prune(t, root_mac, device_types, lldp_forbidden, show_all)
        # print tree and associated messages
        if last_scan is None:
            note_last_scan = NOTE_LAST_NETWORK_SCAN_UNKNOWN
        else:
            delay = time.time() - last_scan
            note_last_scan = NOTE_LAST_NETWORK_SCAN % human_readable_delay(delay)
        tips = TIPS_MIN
        notes = (note_last_scan,)
        if len(all_macs - confirmed_macs) > 0:
            notes = notes + (NOTE_EXPLAIN_UNREACHABLE,)
        if show_all:
            tips = (TIP_DEVICE_ADMIN_1,) + tips
            notes = notes + (NOTE_EXPLAIN_UNKNOWN,)
        else:
            tips = (TIP_ADD_FLAG_ALL,) + tips
        footer = format_explanation('note', notes) + '\n' + format_explanation('tip', tips)
        return "\n%s\n%s" % (t.printed(root=root_mac), footer)

    def prune(self, t, root_mac, device_types, lldp_forbidden, show_all):
        if not show_all:
            # prune parts of the tree with no node
            seen = set()
            def node_count_prune(mac):
                seen.add(mac)
                if device_types[mac] == 'node':
                    count = 1
                else:
                    count = sum(node_count_prune(child_mac) for child_mac in t.children(mac) \
                                       if child_mac not in seen)
                if device_types[mac] == 'switch' and count == 0:
                    t.prune(mac, '[...] ~> no nodes there')
                return count
            node_count_prune(root_mac)
        # prune subtrees where LLDP exploration is not allowed
        # (those subtrees where already ignored when scanning,
        # but this will display an appropriate message to the user)
        for sw_mac in lldp_forbidden:
            t.prune(sw_mac, '[...] ~> forbidden (cf. walt device config)')

class TopologyManager(object):

    def __init__(self, devices, add_or_update_device_cb):
        self.devices = devices
        self.db = devices.db
        self.last_scan = None
        self.add_or_update_device = add_or_update_device_cb

    def cleanup_sysname(self, sysname):
        return re.sub("[^a-z0-9-]+", "-", sysname.split('.')[0])

    def print_message(self, requester, message):
        if requester is not None:
            requester.stdout.write(message + '\n')
            requester.stdout.flush()
        print(message)

    def collect_devices(self, requester, topology, devices):
        for device in devices:
            if device.type == 'server':
                self.collect_connected_devices(requester, topology,
                    "walt server", "localhost", device.mac, const.SERVER_SNMP_CONF)
            elif device.type == 'switch':
                if not device.conf.get('lldp.explore', False):
                    self.print_message(requester,
                        'Querying %-25s FORBIDDEN (see: walt help show device-config)' % device.name)
                    continue
                snmp_conf = { 'version': device.conf.get('snmp.version'),
                              'community': device.conf.get('snmp.community') }
                self.collect_connected_devices(requester, topology,
                    device.name, device.ip, device.mac, snmp_conf)
            else:
                self.print_message(requester,
                    'Querying %-25s INVALID (can only scan switches or the server)' % device.name)

    def collect_connected_devices(self, requester, topology, host_name,
                                    host_ip, host_mac, host_snmp_conf):
        print("Querying %s..." % host_name)
        if host_ip is None:
            self.print_message(requester, "Querying %-25s FAILED (unknown management IP!)" % host_name)
            return
        # get a SNMP proxy object
        try:
            snmp_proxy = snmp.Proxy(host_ip, host_snmp_conf, lldp=True)
        except NoSNMPVariantFound:
            self.print_message(requester, "Querying %-25s FAILED (while trying to probe SNMP variant)" % host_name)
            return
        # get neighbors
        try:
            neighbors = snmp_proxy.lldp.get_neighbors().items()
            self.print_message(requester, "Querying %-25s OK" % host_name)
        except SNMPException:
            self.print_message(requester, "Querying %-25s FAILED (SNMP issue)" % host_name)
            return
        # analyse
        for port, neighbor_info in neighbors:
            ip, mac, sysname =  neighbor_info['ip'], neighbor_info['mac'], \
                                neighbor_info['sysname']
            print('---- found on %s %s -- port %d: %s %s %s' % \
                        (host_name, host_mac, port, ip, mac, sysname))
            topology.register_neighbor(host_mac, port, mac)
            info = dict(mac = mac, ip = ip)
            db_info = self.devices.get_complete_device_info(mac)
            if db_info == None:
                # new device, call add_or_update_device to add it
                name = self.cleanup_sysname(sysname)
                if self.devices.validate_device_name(None, name):   # name seems meaningful...
                    info.update(name = name)
                self.add_or_update_device(**info)
            elif ip != db_info.ip:
                # call add_or_update_device to update ip
                info.update(type = db_info.type, name = db_info.name)
                self.add_or_update_device(**info)

    def rescan(self, requester, remote_ip, devices):
        # note: the last parameter of this method is called "devices" and
        # not "switches" because the server may also be included in this
        # list of devices to be probed.
        self.last_scan = time.time()

        # explore the network equipments
        new_topology = Topology()
        self.collect_devices(requester, new_topology, devices)

        # retrieve past topology data from db
        db_topology = Topology()
        db_topology.load_from_db(self.db)
        db_topology.unconfirm(devices)

        # merge (with priority to new data)
        new_topology.merge_other(db_topology)

        # cleanup conflicting data (obsolete vs confirmed)
        nodes_mac = set(n.mac for n in self.db.select('nodes'))
        new_topology.cleanup(nodes_mac)

        # commit to db
        new_topology.save_to_db(self.db)

    def get_tree_root_mac(self, db_topology):
        # the root of the tree should be the main switch.
        # we analyse the neighbors of this server:
        # - if we find one, we return it
        # - if we find several ones, we favor the ones in
        #   walt-net or walt-adm (thus we discard neighbors found from walt-out)
        # - if we still find several ones, we favor the ones which type is known
        #   as a switch
        server_mac = get_mac_address(const.WALT_INTF)
        unknown_neighbors = []
        for port, neighbor_mac, neighbor_port, confirmed in \
                db_topology.get_neighbors(server_mac):
            info = self.devices.get_complete_device_info(neighbor_mac)
            if info.ip is None:
                continue  # ignore this device
            if not (ip_in_walt_network(info.ip) or ip_in_walt_adm_network(info.ip)):
                continue  # ignore this device
            if info.type == 'unknown':
                unknown_neighbors.append(info.name)
                continue  # possibly the switch we are looking for
            if info.type == 'switch':
                return (True, neighbor_mac)  # Found it!
        # if we are here we did not find what we want
        out = MSG_UNKNOWN_TOPOLOGY
        if len(unknown_neighbors) > 0:
            out += format_sentence("Note: %s was(were) detected, but its(their) type is unknown.\n" +
                                   "If it(one of them) is a switch, use:\n" +
                                   "$ walt device config <device> type=switch\n",
                                   unknown_neighbors, None, 'device', 'devices')
        return (False, out)

    def tree(self, requester, show_all):
        db_topology = Topology()
        db_topology.load_from_db(self.db)
        if db_topology.is_empty():
            return MSG_UNKNOWN_TOPOLOGY
        tree_root_info = self.get_tree_root_mac(db_topology)
        if tree_root_info[0] is False:  # failed
            return tree_root_info[1]    # return error message
        root_mac = tree_root_info[1]
        # compute device mac to label and type associations
        device_labels = { d.mac: d.name for d in self.db.select('devices') }
        device_types = { d.mac: d.type for d in self.db.select('devices') }
        lldp_forbidden = set(d.mac for d in self.db.select('devices', type = 'switch') \
                             if d.conf.get('lldp.explore', False) is False)
        # compute and return the topology tree
        stdout_encoding = requester.stdout.get_encoding()
        return db_topology.printed_tree(self.last_scan, stdout_encoding,
                       root_mac, device_labels, device_types, lldp_forbidden, show_all)

    def nodes_set_poe(self, nodes, poe_status):
        nodes_ok, errors = [], {}
        for node in nodes:
            # we have to know on which PoE switch port the node is
            switch_info, switch_port = self.get_connectivity_info(node.mac)
            # let's request the switch to enable or disable the PoE
            snmp_conf = { 'version': switch_info.conf.get('snmp.version'),
                          'community': switch_info.conf.get('snmp.community') }
            try:
                proxy = snmp.Proxy(switch_info.ip, snmp_conf, poe=True)
                # before trying to turn PoE power off, check if this switch port
                # is actually delivering power.
                if poe_status is False:
                    if not proxy.poe.check_poe_in_use(switch_port):
                        errors[node.name] = 'node seems not PoE-powered'
                        continue
                # turn poe power on or off
                proxy.poe.set_port(switch_port, poe_status)
                nodes_ok.append(node)
            except Exception as e:
                errors[node.name] = str(e).lower()
        return nodes_ok, errors

    def get_connectivity_info(self, device_mac):
        # we look for a record where mac1 or mac2 equals device_mac
        records = list(self.db.select("topology", mac1=device_mac))
        records += list(self.db.select("topology", mac2=device_mac))
        if len(records) != 1:
            return (None, None)
        record = records[0]
        if record.mac1 == device_mac:
             switch_mac, switch_port = record.mac2, record.port2
        else:
             switch_mac, switch_port = record.mac1, record.port1
        switch_info = self.devices.get_complete_device_info(switch_mac)
        return switch_info, switch_port
