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
            d2.name as switch_name, t.switch_port as switch_port
    FROM devices d1
    LEFT JOIN topology t ON d1.mac = t.mac
    LEFT JOIN devices d2 ON t.switch_mac = d2.mac
    ORDER BY switch_name, switch_port;"""

FLOATING_DEVICES_QUERY = """
    SELECT  d1.name as name, d1.type as type, d1.mac as mac,
            d1.ip as ip,
            (case when d1.reachable = 1 then 'yes' else 'NO' end) as reachable
    FROM devices d1 LEFT JOIN topology t
    ON   d1.mac = t.mac
    WHERE t.mac is NULL;"""

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

    def __init__(self, devices):
        self.devices = devices
        self.db = devices.db

    def collect_connected_devices(self, ui, host, host_depth,
                            host_mac, processed_switches):

        print "collect devices connected on %s" % host
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
                if neighbors_depth == 1:
                    # main switch is the root of the topology tree
                    switch_mac, switch_port = None, None
                else:
                    switch_mac, switch_port = host_mac, port
                self.update_device_topology(
                                mac=mac,
                                switch_mac=switch_mac,
                                switch_port=switch_port)
                if device_type == 'switch' and mac not in processed_switches:
                    # recursively discover devices connected to this switch
                    self.collect_connected_devices(ui, ip, neighbors_depth,
                                            mac, processed_switches)
            if not issue:
                break   # otherwise restart the loop

    def rescan(self, requester=None, remote_ip=None, ui=None):
        # register the server in the device list, if missing
        server_mac = get_mac_address(const.WALT_INTF)
        self.devices.add_if_missing(
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
        self.collect_connected_devices(ui, "localhost", 0, server_mac, set())
        # commit
        self.db.commit()
        # notify the client
        if requester != None:
            requester.stdout.write('done.\n')

    def update_device_topology(self, mac, switch_mac, switch_port):
        # if we are there then we can reach this device
        self.db.update('devices', 'mac', mac = mac, reachable = 1)
        # add/update topology info:
        # - update or insert topology info for device with specified mac
        # - if any other device was connected at this place, it will
        #   be replaced (thus this other device will appear disconnected)
        self.db.delete('topology', mac = mac)
        self.db.delete('topology', switch_mac = switch_mac,
                                   switch_port = switch_port)
        self.db.insert("topology", mac = mac,
                                   switch_mac = switch_mac,
                                   switch_port = switch_port)

    def tree(self):
        t = Tree()
        unreachable_found = False
        main_switch_name = None
        for device in self.db.execute(TOPOLOGY_QUERY).fetchall():
            name = device.name
            decorated_name = name
            if device.reachable == 'NO':
                unreachable_found = True
                decorated_name = '(%s)' % name
            swport = device.switch_port
            if swport == None:
                label = decorated_name
                # align to 2nd letter of the name
                subtree_offset = 1
            else:
                label = '%d: %s' % (swport, decorated_name)
                # align to 2nd letter of the name
                subtree_offset = label.find(' ') + 2
            parent_key = device.switch_name
            t.add_node( name,   # will be the key in the tree
                        label,
                        subtree_offset=subtree_offset,
                        parent_key = parent_key)
            if device.type == 'server':
                main_switch_name = device.switch_name
        note = MSG_DEVICE_TREE_MORE_DETAILS
        if unreachable_found:
            note += MSG_DEVICE_TREE_EXPLAIN_UNREACHABLE
        return "\n%s%s" % (t.printed(root=main_switch_name), note)

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
