#!/usr/bin/env python

from walt.common.tools import get_mac_address
from walt.common.nodetypes import get_node_type_from_mac_address
from walt.common.nodetypes import is_a_node_type_name
from walt.server.network.tools import ip_in_walt_network, lldp_update
from walt.server.tools import format_paragraph
import snmp, const, time, re
from tree import Tree
import walt.server

DEVICE_NAME_NOT_FOUND="""No device with name '%s' found.\n"""

TOPOLOGY_QUERY = """
    SELECT  d1.name as name, d1.type as type, d1.mac as mac,
            d1.ip as ip, d1.reachable as reachable,
            d2.name as switch_name, t.switch_port as switch_port
    FROM devices d1, devices d2, topology t
    WHERE   d1.mac = t.mac and d2.mac = t.switch_mac
    UNION ALL
    SELECT  d1.name as name, d1.type as type, d1.mac as mac,
            d1.ip as ip, d1.reachable as reachable,
            NULL as switch_name, NULL as switch_port
    FROM devices d1, topology t
    WHERE   d1.mac = t.mac and t.switch_mac is null
    ORDER BY switch_name, switch_port;"""

DISCONNECTED_DEVICES_QUERY = """
    SELECT  d1.name as name, d1.type as type, d1.mac as mac,
            d1.ip as ip
    FROM devices d1 LEFT JOIN topology t
    ON   d1.mac = t.mac
    WHERE t.mac is NULL;"""

MSG_DEVICE_SHOW_MORE_DETAILS = """
(tip: use --details option for more info)
"""

TITLE_DEVICE_SHOW_DETAILS_MAIN = """\
The WalT network contains the following devices:"""

TITLE_DEVICE_SHOW_DETAILS_DISCONNECTED = """\
The following devices are currently disconnected:"""

FOOTNOTE_DEVICE_SHOW_DETAILS_DISCONNECTED = """\
(tip: walt device forget <device_name>)"""

NEW_NAME_ERROR_AND_GUIDELINES = """\
Failed: invalid new name.
This name must be a valid network hostname. 
Only alphanumeric characters and '-' are allowed.
The 1st character must be an alphabet letter.
(Example: rpi-D327)
"""

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

    def collect_connected_devices(self, host, host_is_a_switch,
                            host_mac, processed_switches):

        print "collect devices connected on %s" % host
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
                if mac in processed_switches:
                    continue
                if not ip_in_walt_network(ip):
                    print 'Not ready, one neighbor has ip %s (not in WalT network yet)...' % ip
                    lldp_update()
                    time.sleep(1)
                    issue = True
                    break
                device_type = self.get_type(mac)
                if host_is_a_switch:
                    switch_mac, switch_port = host_mac, port
                else:
                    switch_mac, switch_port = None, None
                self.add_device(type=device_type,
                                mac=mac,
                                switch_mac=switch_mac,
                                switch_port=switch_port,
                                ip=ip)
                if device_type == 'switch':
                    # recursively discover devices connected to this switch
                    self.collect_connected_devices(ip, True,
                                            mac, processed_switches)
            if not issue:
                break   # otherwise restart the loop

    def update(self, requester=None):
        # delete some information that will be updated
        self.db.execute('DELETE FROM topology;')
        self.db.execute("""
            UPDATE devices
            SET reachable = 0;""")

        self.server_mac = get_mac_address(const.SERVER_TESTBED_INTERFACE)
        self.collect_connected_devices("localhost", False, self.server_mac, set())
        self.db.commit()

        if requester != None:
            requester.stdout.write('done.\n')

    def get_device_info(self, requester, device_name, \
                        err_message = DEVICE_NAME_NOT_FOUND):
        device_info = self.db.select_unique("devices", name=device_name)
        if device_info == None and err_message != None:
            requester.stderr.write(err_message % device_name)
        return device_info

    def get_node_info(self, requester, node_name):
        node_info = self.get_device_info(requester, node_name)
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
                self.update()   # rescan, just in case
                return self.get_reachable_node_info(
                        requester, node_name, after_rescan = True)
        return node_info

    def notify_unknown_ip(self, requester, device_name):
        requester.stderr.write('Sorry, IP address of %s in unknown.\n' \
                            % device_name)

    def get_device_ip(self, requester, device_name):
        device_info = self.get_device_info(requester, device_name)
        if device_info == None:
            return None # error already reported
        if device_info.ip == None:
            self.notify_unknown_ip(requester, device_name)
        return device_info.ip

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

    def get_connectivity_info(self, requester, node_name):
        node_info = self.get_reachable_node_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        node_mac = node_info.mac
        topology_info = self.db.select_unique("topology", mac=node_mac)
        switch_mac = topology_info.switch_mac
        switch_port = topology_info.switch_port
        switch_info = self.db.select_unique("devices", mac=switch_mac)
        return dict(
            switch_ip = switch_info.ip,
            switch_port = switch_port
        )

    def rename_device(self, requester, old_name, new_name):
        device_info = self.get_device_info(requester, old_name)
        if device_info == None:
            return
        if self.get_device_info(requester, new_name, err_message = None) != None:
            requester.stderr.write("""Failed: a device with name '%s' already exists.\n""" % new_name)
            return
        if not re.match('^[a-zA-Z][a-zA-Z0-9-]*$', new_name):
            requester.stderr.write(NEW_NAME_ERROR_AND_GUIDELINES)
            return
        # all is fine, let's update it
        self.db.update("devices", 'mac', mac = device_info.mac, name = new_name)
        self.db.commit()

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
            # add topology info
            self.db.insert("topology", **kwargs)

    def printed_as_tree(self):
        t = Tree()
        for device in self.db.execute(TOPOLOGY_QUERY).fetchall():
            name = device.name
            swport = device.switch_port
            if swport == None:
                label = name
                # align to 2nd letter of the name
                subtree_offset = 1
            else:
                label = '%d: %s' % (swport, name)
                # align to 2nd letter of the name
                subtree_offset = label.find(' ') + 2
            parent_key = device.switch_name
            t.add_node( name,   # will be the key in the tree
                        label,
                        subtree_offset=subtree_offset,
                        parent_key = parent_key)
        return "\n%s%s" % (
            t.printed(), MSG_DEVICE_SHOW_MORE_DETAILS)

    def printed_as_detailed_table(self):
        # message about connected devices
        msg = format_paragraph(
                TITLE_DEVICE_SHOW_DETAILS_MAIN,
                self.db.pretty_printed_select(TOPOLOGY_QUERY))
        # message about disconnected devices, if at least one
        res = self.db.execute(DISCONNECTED_DEVICES_QUERY).fetchall()
        if len(res) > 0:
            msg += format_paragraph(
                        TITLE_DEVICE_SHOW_DETAILS_DISCONNECTED,
                        self.db.pretty_printed_resultset(res),
                        FOOTNOTE_DEVICE_SHOW_DETAILS_DISCONNECTED)
        return msg

    def is_disconnected(self, device_name):
        res = self.db.execute("""
            SELECT count(*)
            FROM devices d, topology t
            WHERE d.name = %s AND d.mac = t.mac;""",
            (device_name,)).fetchall()
        return res[0][0] == 0
