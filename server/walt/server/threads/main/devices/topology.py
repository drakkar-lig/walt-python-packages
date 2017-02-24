#!/usr/bin/env python

import time

from walt.common.tools import get_mac_address
from walt.server import const
from walt.server.threads.main import snmp
from walt.server.threads.main.network.tools import ip_in_walt_network, lldp_update, \
               set_static_ip_on_switch, restart_dhcp_setup_on_switch, get_server_ip
from walt.server.threads.main.tree import Tree
from walt.server.tools import format_paragraph


TOPOLOGY_QUERY = """
    SELECT  d1.name as name, d1.type as type, d1.mac as mac,
            d1.ip as ip,
            (case when d1.reachable = 1 then 'yes' else 'NO' end) as reachable,
            d2.name as switch_name, t.port1 as switch_port
    FROM devices d1
    LEFT JOIN topology t ON d1.mac = t.mac2
    LEFT JOIN devices d2 ON t.mac1 = d2.mac
    ORDER BY switch_name, switch_port;"""

FLOATING_DEVICES_QUERY = """
    SELECT  d1.name as name, d1.type as type, d1.mac as mac,
            d1.ip as ip,
            (case when d1.reachable = 1 then 'yes' else 'NO' end) as reachable
    FROM devices d1 LEFT JOIN topology t
    ON   d1.mac = t.mac2
    WHERE t.mac2 is NULL;"""

MSG_DEVICE_TREE_EXPLAIN_UNREACHABLE = """\
note: devices marked with parentheses are unreachable
"""

MSG_DEVICE_TREE_MORE_DETAILS = """
tips:
- use 'walt device rescan' to update
- use 'walt device show' for more info
"""

TITLE_DEVICE_SHOW_MAIN = """\
The WalT network contains the following devices:"""

FOOTNOTE_DEVICE_SHOW_MAIN = """\
tips:
- use 'walt device tree' for a tree view of the network
- use 'walt device rescan' to update
- use 'walt device forget <device_name>' in case of a broken device"""

TITLE_DEVICE_SHOW_FLOATING = """\
The network position of the following devices is unknown (at least for now):"""

FOOTNOTE_DEVICE_SHOW_FLOATING = """\
tips:
- use 'walt device rescan' in a few minutes to update
- use 'walt device forget <device_name>' to make WalT forget about an obsolete device"""

class Topology(object):
    def __init__(self):
        # links as a dict (mac1, mac2) -> (port1, port2, confirmed)
        self.links = {}

    def register_neighbor(self, local_mac, local_port, neighbor_mac):
        mac1 = min(local_mac, neighbor_mac)
        mac2 = max(local_mac, neighbor_mac)
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
        for link_macs, link_info in self.links.iteritems():
            db.insert('topology',   mac1 = link_macs[0],
                                    mac2 = link_macs[1],
                                    port1 = link_info[0],
                                    port2 = link_info[1],
                                    confirmed = link_info[2])
        db.commit()

    def unconfirm_all(self):
        new_links = {}
        for k in self.links:
            port1, port2, confirmed = self.links[k]
            new_links[k] = port1, port2, False
        self.links = new_links

    def __iter__(self):
        # iterate over links info
        for macs, info in self.links.iteritems():
            yield macs + info   # concatenate the tuples

    def merge_other(self, other):
        # build the union of 'self.links' and 'other.links';
        # in case of conflict, keep the one which has the
        # 'confirmed' flag set.
        new_links = {}
        keys_self = set(self.links)
        keys_other = set(other.links)
        common_keys = keys_self & keys_other
        for k in common_keys:
            # check which one is confirmed
            if self.links[k][2] < other.links[k][2]:
                winner = other
            else:
                winner = self
            new_links[k] = winner.links[k]
        for k in keys_self - keys_other:
            new_links[k] = self.links[k]
        for k in keys_other - keys_self:
            new_links[k] = other.links[k]
        # check if we have several links at the same location
        # (mac, port), and in this case keep the one confirmed.
        locations = {}
        for macs, info in new_links.copy().iteritems():
            mac1, mac2, port1, port2, confirmed = macs + info
            conflicting_mac2 = locations.get((mac1, port1))
            if conflicting_mac2 is not None:
                if confirmed: # this one is confirmed, discard the old one
                    new_links.pop((mac1, conflicting_mac2), None)
                else:         # this one is not confirmed, discard it
                    new_links.pop((mac1, mac2), None)
            else:
                locations[(mac1, port1)] = mac2
            conflicting_mac1 = locations.get((mac2, port2))
            if conflicting_mac1 is not None:
                if confirmed: # this one is confirmed, discard the old one
                    new_links.pop((conflicting_mac1, mac2), None)
                else:         # this one is not confirmed, discard it
                    new_links.pop((mac1, mac2), None)
            else:
                locations[(mac2, port2)] = mac1
        self.links = new_links

    def cleanup(self):
        # this will remove obsolete links from moved devices,
        # and ensure we have no loops.
        # 1) we build the set of confirmed nodes (nodes that
        #    were detected during last scan)
        confirmed_macs = set()
        for mac1, mac2, port1, port2, confirmed in self:
            if confirmed:
                confirmed_macs.add(mac1)
                confirmed_macs.add(mac2)
        # 2) we drop unconfirmed links linking 2 confirmed nodes
        to_be_dropped = []
        for mac1, mac2, port1, port2, confirmed in self:
            if not confirmed and \
                    mac1 in confirmed_macs and mac2 in confirmed_macs:
                to_be_dropped.append((mac1, mac2))
        for k in to_be_dropped:
            self.links.pop(k)

    def get_neighbors(self, mac):
        for mac1, mac2 in self.links:
            if mac in (mac1, mac2):
                port1, port2, confirmed = self.links[(mac1, mac2)]
            if mac1 == mac:
                yield port1, mac2, port2, confirmed
            if mac2 == mac:
                yield port2, mac1, port1, confirmed

    def printed_tree(self, root_mac, device_labels, device_types):
        t = Tree()
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
        for mac in confirmed_macs:
            t.add_node(mac, device_labels[mac])
        for mac in all_macs - confirmed_macs:   # not confirmed
            t.add_node(mac, '(%s)' % device_labels[mac])
        # declare children
        for mac1, mac2, port1, port2, confirmed in self:
            for node_mac, parent_mac, parent_port in \
                    ((mac1, mac2, port2), (mac2, mac1, port1)):
                if device_types[parent_mac] == 'switch':
                    t.add_child(parent_mac, parent_port, node_mac)
        # print tree and associated messages
        note = MSG_DEVICE_TREE_MORE_DETAILS
        if len(all_macs - confirmed_macs) > 0:
            note += MSG_DEVICE_TREE_EXPLAIN_UNREACHABLE
        return "\n%s%s" % (t.printed(root=root_mac), note)

class TopologyManager(object):

    def __init__(self, devices):
        self.devices = devices
        self.db = devices.db

    def collect_connected_devices(self, ui, topology, host, host_depth,
                            host_mac, processed_switches):

        print "collecting on %s %s" % (host, host_mac)
        switches_with_dhcp_restarted = set()
        switches_with_wrong_ip = set()
        # avoid to loop forever...
        if host_depth > 0:
            processed_switches.add(host_mac)
        neighbors_depth = host_depth + 1
        while True:
            issue = False
            # get a SNMP proxy with LLDP feature
            snmp_proxy = snmp.Proxy(host, lldp=True)

            # record neighbors in db and recurse
            for port, neighbor_info in snmp_proxy.lldp.get_neighbors().items():
                # ignore neighbors on port 1 of the main switch
                # (port 1 is associated to VLAN walt-out)
                if neighbors_depth == 2 and port < 2:
                    continue
                ip, mac = neighbor_info['ip'], neighbor_info['mac']
                print '---- found on %s %s -- port %d: %s %s' % (host, host_mac, port, ip, mac)
                device_type = self.devices.get_type(mac)
                if device_type == None:
                    # this device did not get a dhcp lease?
                    print 'Warning: Unregistered device with mac %s detected on %s\'s port %d. Ignoring.' % \
                                (mac, host, port)
                    continue
                valid_ip = str(ip) != 'None'
                if not valid_ip or not ip_in_walt_network(ip):
                    # if someone is viewing the UI, let him know that we are still
                    # alive, because this could cause a long delay.
                    if ui:
                        ui.task_running()
                    print 'Not ready, one neighbor has ip %s (not in WalT network yet)...' % ip
                    if device_type == 'switch' and valid_ip:
                        if mac not in switches_with_dhcp_restarted:
                            print 'trying to restart the dhcp client on switch %s (%s)' % (ip, mac)
                            switches_with_dhcp_restarted.add(mac)
                            restart_dhcp_setup_on_switch(ip)
                        switches_with_wrong_ip.add(mac)
                    lldp_update()
                    time.sleep(1)
                    issue = True
                    break
                elif valid_ip and ip_in_walt_network(ip):
                    if mac in switches_with_wrong_ip:
                        switches_with_wrong_ip.discard(mac)
                        print 'Affecting static IP configuration on switch %s (%s)...' % \
                            (ip, mac)
                        set_static_ip_on_switch(ip)
                topology.register_neighbor(host_mac, port, mac)
                if device_type == 'switch' and mac not in processed_switches:
                    # recursively discover devices connected to this switch
                    self.collect_connected_devices(ui, topology, ip, neighbors_depth,
                                            mac, processed_switches)
            if not issue:
                break   # otherwise restart the loop

    def rescan(self, requester=None, remote_ip=None, ui=None):
        # register the server in the device list, if missing
        server_mac = get_mac_address(const.WALT_INTF)
        self.devices.add_or_update(
                mac = server_mac, ip = str(get_server_ip()),
                device_type = 'server')
        reachable_filters = [ "type = 'server'" ]
        # if the client is connected on the walt network, set it as reachable
        if remote_ip:
            reachable_filters.append("ip = '%s'" % remote_ip)
        # initialize all devices to unreachable except selected ones
        self.db.execute("UPDATE devices SET reachable = 0;")
        self.db.execute("UPDATE devices SET reachable = 1 WHERE %s;" % \
                            " OR ".join(reachable_filters))
        # explore the network
        new_topology = Topology()
        self.collect_connected_devices(ui, new_topology, "localhost", 0, server_mac, set())

        # retrieve past topology data from db
        db_topology = Topology()
        db_topology.load_from_db(self.db)
        db_topology.unconfirm_all()

        # merge (with priority to new data)
        new_topology.merge_other(db_topology)
        new_topology.cleanup()

        # commit to db
        new_topology.save_to_db(self.db)

        # notify the client
        if requester != None:
            requester.stdout.write('done.\n')

    def tree(self):
        db_topology = Topology()
        db_topology.load_from_db(self.db)
        # the root of the tree should be the main switch.
        # this is the unique neighbor of this server.
        server_mac = get_mac_address(const.WALT_INTF)
        root_mac = None
        for port, neighbor_mac, neighbor_port, confirmed in \
                db_topology.get_neighbors(server_mac):
            root_mac = neighbor_mac
        # compute device mac to label and type associations
        device_labels = { d.mac: d.name for d in self.db.select('devices') }
        device_types = { d.mac: d.type for d in self.db.select('devices') }
        # compute and return the topology tree
        return db_topology.printed_tree(root_mac, device_labels, device_types)

    def show(self):
        # ** message about connected devices
        msg = format_paragraph(
                TITLE_DEVICE_SHOW_MAIN,
                self.db.pretty_printed_select(TOPOLOGY_QUERY),
                FOOTNOTE_DEVICE_SHOW_MAIN)
        # ** message about floating devices, if at least one
        res = self.db.execute(FLOATING_DEVICES_QUERY).fetchall()
        if len(res) > 0:
            msg += format_paragraph(
                        TITLE_DEVICE_SHOW_FLOATING,
                        self.db.pretty_printed_resultset(res),
                        FOOTNOTE_DEVICE_SHOW_FLOATING)
        return msg

    def setpower(self, device_mac, poweron):
        # we have to know on which PoE switch port the node is
        switch_ip, switch_port = self.get_connectivity_info(device_mac)
        if not switch_ip:
            return False
        # if powering off, the device will be unreachable
        if not poweron:
            self.db.update('devices', 'mac', mac=device_mac, reachable=0)
            self.db.commit()
        # let's request the switch to enable or disable the PoE
        proxy = snmp.Proxy(switch_ip, poe=True)
        proxy.poe.set_port(switch_port, poweron)
        return True

    def get_connectivity_info(self, device_mac):
        topology_info = self.db.select_unique("topology", mac=device_mac)
        if not topology_info:
            return (None, None)
        switch_mac = topology_info.switch_mac
        switch_port = topology_info.switch_port
        switch_info = self.db.select_unique("devices", mac=switch_mac)
        return switch_info.ip, switch_port
