#!/usr/bin/env python

from walt.common.tools import get_mac_address
from walt.server.sqlite import MemoryDB
from walt.common.nodetypes import get_node_type_from_mac_address
from walt.common.nodetypes import is_a_node_type_name
import snmp

# TODO: get the following from the platform configuration
SERVER_TESTBED_INTERFACE="eth0"
POE_REBOOT_DELAY=2  # seconds

class TopologyDB(MemoryDB):

    def __init__(self):
        # parent constructor
        MemoryDB.__init__(self)
        # create the db schema
        self.execute("""CREATE TABLE network
                 (type TEXT, mac TEXT PRIMARY KEY, ip TEXT, switch_ip TEXT, switch_port TEXT);""")

    def show(self):
        print self.printed()

    def try_add_device(self, **kwargs):
        return self.try_insert("network", **kwargs)

    def add_device(self, **kwargs):
        self.try_add_device(**kwargs) # ignore the result

    def get_device_info(self, **kwargs):
        device_info_list = self.select("network", **kwargs)
        if len(device_info_list) == 0:
            return None
        else:
            return device_info_list[0]

    def printed(self):
        return self.table_dump("network")


class PoEPlatform(object):

    def __init__(self):
        self.update()

    def get_type(self, mac, server_mac):
        node_type = get_node_type_from_mac_address(mac)
        if node_type != None:
            # this is a node
            return node_type.SHORT_NAME
        elif mac == server_mac:
            return 'server'
        else:
            return 'switch'

    def collect_connected_devices(self, host, host_is_a_switch, server_mac):

        # get a SNMP proxy with LLDP feature
        snmp_proxy = snmp.Proxy(host, lldp=True)

        # record neighbors in db and recurse
        for port, neighbor_info in snmp_proxy.lldp.get_neighbors().items():
            ip, mac = neighbor_info['ip'], neighbor_info['mac']
            device_type = self.get_type(mac, server_mac)
            if host_is_a_switch:
                switch_ip, switch_port = host, port
            else:
                switch_ip, switch_port = None, None
            new_device = self.db.try_add_device(
                            type=device_type,
                            mac=mac,
                            switch_ip=switch_ip,
                            switch_port=switch_port,
                            ip=ip)
            if new_device and device_type == 'switch':
                # recursively discover devices connected to this switch
                self.collect_connected_devices(ip, True, server_mac)

    def update(self, requester=None):
        # Let's go
        self.db = TopologyDB()

        server_mac = get_mac_address(SERVER_TESTBED_INTERFACE)
        self.collect_connected_devices("localhost", False, server_mac)

        if requester != None:
            requester.write_stdout('done.\n')

    def describe(self):
        return self.db.printed()

    def reboot_node(self, requester, ip_address):
        node_info = self.db.get_device_info(ip=ip_address)
        if node_info == None:
            requester.write_stderr('No such node found.\n')
        else:
            device_type = node_info['type']
            if not is_a_node_type_name(device_type):
                requester.write_stderr('%s is not a node, it is a %s.\n' % (ip_address, device_type))
            else:   # all is fine, let's reboot it
                proxy = snmp.Proxy(node_info['switch_ip'], poe=True)
                self.poe_reboot_port(proxy, node_info['switch_port'])
                requester.write_stdout('done.\n')

    def poe_reboot_port(self, poe_proxy, switch_port):
        proxy.set_port(switch_port, False)
        time.sleep(POE_REBOOT_DELAY)
        proxy.set_port(switch_port, True)

