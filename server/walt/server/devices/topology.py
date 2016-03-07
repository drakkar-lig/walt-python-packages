#!/usr/bin/env python

from walt.common.tools import get_mac_address
from walt.common.nodetypes import get_node_type_from_mac_address
from walt.server.network.tools import ip_in_walt_network, lldp_update, \
                                        restart_dhcp_setup_on_switch, \
                                        set_static_ip_on_switch
from walt.server.tools import format_paragraph, columnate
from walt.server.tree import Tree
from walt.server import snmp, const
import time, re

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

    def __init__(self, db):
        self.db = db

    def get_type(self, mac):
        node_type = get_node_type_from_mac_address(mac)
        if node_type != None:
            # this is a node
            return node_type.SHORT_NAME
        elif mac == self.server_mac:
            return 'server'
        else:
            return 'switch'

    def collect_connected_devices(self, ui, host, host_is_a_switch,
                            host_mac, processed_switches):

        print "collect devices connected on %s" % host
        switches_with_dhcp_restarted = set()
        # avoid to loop forever...
        if host_is_a_switch:
            processed_switches.add(host_mac)
        while True:
            issue = False
            # get a SNMP proxy with LLDP feature
            snmp_proxy = snmp.Proxy(host, lldp=True)

            # record neighbors in db and recurse
            for port, neighbor_info in snmp_proxy.lldp.get_neighbors().items():
                ip, mac = neighbor_info['ip'], neighbor_info['mac']
                device_type = self.get_type(mac)
                if mac in processed_switches:
                    continue
                valid_ip = str(ip) != 'None'
                if not valid_ip or not ip_in_walt_network(ip):
                    # if someone is viewing the UI, let him know that we are still
                    # alive, because this could cause a long delay.
                    if ui:
                        ui.task_running()
                    print 'Not ready, one neighbor has ip %s (not in WalT network yet)...' % ip
                    if valid_ip and device_type == 'switch' and \
                            mac not in switches_with_dhcp_restarted:
                        print 'trying to restart the dhcp client on switch %s (%s)' % (ip, mac)
                        switches_with_dhcp_restarted.add(mac)
                        restart_dhcp_setup_on_switch(ip)
                    lldp_update()
                    time.sleep(1)
                    issue = True
                    break
                if host_is_a_switch:
                    switch_mac, switch_port = host_mac, port
                else:
                    switch_mac, switch_port = None, None
                device_is_new = self.add_device(type=device_type,
                                mac=mac,
                                switch_mac=switch_mac,
                                switch_port=switch_port,
                                ip=ip)
                if device_type == 'switch':
                    if device_is_new:
                        print 'Affecting static IP configuration on switch %s (%s)...' % \
                            (ip, mac)
                        set_static_ip_on_switch(ip)
                    # recursively discover devices connected to this switch
                    self.collect_connected_devices(ui, ip, True,
                                            mac, processed_switches)
            if not issue:
                break   # otherwise restart the loop

    def rescan(self, requester=None, ui=None):
        self.db.execute("""
            UPDATE devices
            SET reachable = 0;""")

        self.server_mac = get_mac_address(const.WALT_INTF)
        self.collect_connected_devices(ui, "localhost", False, self.server_mac, set())
        self.db.commit()

        if requester != None:
            requester.stdout.write('done.\n')

    def generate_device_name(self, **kwargs):
        if kwargs['type'] == 'server':
            return 'walt-server'
        return "%s-%s" %(
            kwargs['type'],
            "".join(kwargs['mac'].split(':')[3:]))

    def add_device(self, **kwargs):
        # if we are there then we can reach this device
        kwargs['reachable'] = 1
        # update device info
        num_rows = self.db.update("devices", 'mac', **kwargs)
        # if no row was updated, this is a new device
        if num_rows == 0:
            # generate a name for this device
            name = self.generate_device_name(**kwargs)
            kwargs['name'] = name
            # insert a new row
            self.db.insert("devices", **kwargs)
        if 'switch_mac' in kwargs:
            mac = kwargs['mac']
            switch_mac = kwargs['switch_mac']
            switch_port = kwargs['switch_port']
            # add/update topology info:
            # - update or insert topology info for device with specified mac
            # - if any other device was connected at this place, it will
            #   be replaced (thus this other device will appear disconnected)
            self.db.delete('topology', mac = mac)
            self.db.delete('topology', switch_mac = switch_mac,
                                       switch_port = switch_port)
            self.db.insert("topology", **kwargs)
        return num_rows == 0 # return True if new device

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
