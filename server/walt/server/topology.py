#!/usr/bin/env python

from plumbum.cmd import lldpctl, grep, awk, snmpwalk, snmpset
from walt.common.tools import eval_cmd, get_mac_address
from walt.server.sqlite import MemoryDB
from walt.common.nodetypes import get_node_type_from_mac_address
from walt.common.nodetypes import is_a_node_type_name
                                    
import sys, rpyc, time

#########################################
# To run this script, you need :        #
# - snmp tools and sqlite on the server #
#   apt-get install snmp sqlite3        #
# - lldpd on both server and RPi        #
#   apt-get install lldpd               #
#########################################

# TODO: get the following from the platform configuration
SERVER_TESTBED_INTERFACE="eth1"
OID_lldpRemChassisIdSubtype="1.0.8802.1.1.2.1.4.1.1.4"
OID_lldpRemChassisId="1.0.8802.1.1.2.1.4.1.1.5"
OID_lldpRemManAddrIfSubtype="1.0.8802.1.1.2.1.4.2.1.3"
OID_pethPsePortAdminEnable="1.3.6.1.4.1.4526.11.16.1.1.1.3"
SNMP_VERSION=1
SNMP_COMMUNITY="private"
POE_PORT_ENABLED=1
POE_PORT_DISABLED=2
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

    def get_main_switch_ip_and_mac(self):
        return (
            eval_cmd(lldpctl | grep['MgmtIP'] | awk['{ print $NF }']).strip(),
            eval_cmd(lldpctl | grep['ChassisID'] | awk['{ print $NF }']).strip()
        )

    def snmp_query(self, switch_ip, oid):
        return eval_cmd(snmpwalk["-c", SNMP_COMMUNITY, "-v", SNMP_VERSION, switch_ip, oid]).splitlines()

    def get_type(self, mac, server_mac):
        node_type = get_node_type_from_mac_address(mac)
        if node_type != None:
            # this is a node
            return node_type.SHORT_NAME
        elif mac == server_mac:
            return 'server'
        else:
            return 'switch'

    def collect_devices_connected_to_switch(self, switch_ip, server_mac):

        chassis_per_port = {}
        ip_per_port = {}

        for chassis_id_desc in self.snmp_query(switch_ip, OID_lldpRemChassisIdSubtype):
            words = chassis_id_desc.split()
            port = int(words[0][-1])
            chassis_per_port[port] = int(words[-1])

        for addr_desc in self.snmp_query(switch_ip, OID_lldpRemManAddrIfSubtype):
            words = addr_desc.split()
            addr_type = int(words[-1])
            # Check if addr type is IP address (2)
            if addr_type == 2:
                port = int(words[0].split('.')[-7])
                ip = '.'.join(words[0].split('.')[-4::])
                ip_per_port[port] = ip

        for chassis_desc in self.snmp_query(switch_ip, OID_lldpRemChassisId):
            words = chassis_desc.split()
            port = int(words[0][-1])
            # Check if chassis type is a MAC address (4)
            if chassis_per_port[port] == 4:
                mac = ":".join(words[-6::]).lower()
                device_type = self.get_type(mac, server_mac)
                ip = ip_per_port[port]
                new_device = self.db.try_add_device(
                    type=device_type, mac=mac, switch_ip=switch_ip, switch_port=port, ip=ip)
                if new_device and device_type == 'switch':
                    # recursively discover devices connected to this switch
                    self.collect_devices_connected_to_switch(ip, server_mac)

    def update(self, requester=None):
        # Let's go
        self.db = TopologyDB()

        main_switch_ip, main_switch_mac = self.get_main_switch_ip_and_mac()
        self.db.add_device(type='switch', ip=main_switch_ip, mac=main_switch_mac)

        server_mac = get_mac_address(SERVER_TESTBED_INTERFACE)
        self.collect_devices_connected_to_switch(main_switch_ip, server_mac)

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
                self.poe_reboot_port(node_info['switch_ip'], node_info['switch_port'])
                requester.write_stdout('done.\n')

    def poe_reboot_port(self, switch_ip, switch_port):
        self.poe_set_port(switch_ip, switch_port, False)
        time.sleep(POE_REBOOT_DELAY)
        self.poe_set_port(switch_ip, switch_port, True)

    def poe_set_port(self, switch_ip, switch_port, active_or_not):
        oid = OID_pethPsePortAdminEnable + '.1.' + str(switch_port)
        port_state = POE_PORT_ENABLED if active_or_not else POE_PORT_DISABLED
        eval_cmd(snmpset["-c", SNMP_COMMUNITY, "-v", SNMP_VERSION, switch_ip, oid, 'i', port_state])
        


