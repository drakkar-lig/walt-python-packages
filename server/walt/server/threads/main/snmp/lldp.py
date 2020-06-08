#!/usr/bin/env python
import re
from walt.server.threads.main.snmp.mibs import load_mib, unload_mib
from walt.server.threads.main.snmp.base import decode_ipv4_address, \
                    decode_mac_address, enum_label, Variant, VariantsSet, VariantProxy

class StandardLLDP(Variant):
    @staticmethod
    def test_or_exception(snmp_proxy):
        dict(snmp_proxy.lldpRemChassisIdSubtype)

    @staticmethod
    def load():
        load_mib(b"LLDP-MIB")

    @staticmethod
    def unload():
        unload_mib(b"LLDP-MIB")

    @staticmethod
    def get_neighbors(snmp_proxy):

        mac_per_port = {}
        ip_per_port = {}
        sysname_per_port = {}

        # perform SNMP requests
        chassis_types = dict(snmp_proxy.lldpRemChassisIdSubtype)
        chassis_values = dict(snmp_proxy.lldpRemChassisId)
        sys_names = dict(snmp_proxy.lldpRemSysName)
        ip_info = list(snmp_proxy.lldpRemManAddrIfSubtype)

        # retrieve mac address and sysname of neighbors
        for neighbor_key in chassis_types:
            if enum_label(chassis_types[neighbor_key]) == 'macAddress':
                timeMark, port, index = neighbor_key
                port = int(port)
                mac_per_port[port] = decode_mac_address(
                                chassis_values[neighbor_key])
                if neighbor_key in sys_names:
                    sysname_per_port[port] = str(sys_names[neighbor_key])
                else:
                    sysname_per_port[port] = ''

        # retrieve ip addresses of neighbors
        for neighbor_ip_info in ip_info:
            timeMark, port, index, subtype, encoded_ip = neighbor_ip_info
            if enum_label(subtype).lower() == 'ipv4':
                ip_per_port[int(port)] = decode_ipv4_address(encoded_ip)

        # merge info
        neighbors = {}
        for port, mac in mac_per_port.items():
            ip = ip_per_port[port] if port in ip_per_port else None
            sysname = sysname_per_port[port]
            neighbors[port] = { 'mac': mac, 'ip': ip, 'sysname': sysname }

        return neighbors

class TPLinkLLDP(Variant):
    @staticmethod
    def test_or_exception(snmp_proxy):
        dict(snmp_proxy.lldpNeighborChassisIdType)

    @staticmethod
    def load():
        load_mib(b"TPLINK-MIB")
        load_mib(b"TPLINK-LLDP-MIB")
        load_mib(b"TPLINK-LLDPINFO-MIB")

    @staticmethod
    def unload():
        unload_mib(b"TPLINK-LLDPINFO-MIB")
        unload_mib(b"TPLINK-LLDP-MIB")
        unload_mib(b"TPLINK-MIB")

    @staticmethod
    def get_neighbors(snmp_proxy):

        mac_per_port = {}
        sysname_per_port = {}
        neighbors = {}

        # perform SNMP requests
        chassis_types = dict(snmp_proxy.lldpNeighborChassisIdType)
        chassis_values = dict(snmp_proxy.lldpNeighborChassisId)
        sys_names = dict(snmp_proxy.lldpNeighborDeviceName)
        port_info = dict(snmp_proxy.lldpLocalPortId)

        # retrieve mac address and sysname of neighbors
        for neighbor_key in chassis_types:
            if bytes(chassis_types[neighbor_key]) == b'MAC address':
                port_id, index = neighbor_key
                port_str = bytes(port_info[int(port_id)]).decode('ascii')
                port = int(re.split(r'[^\d]+', port_str)[-1])
                mac = bytes(chassis_values[neighbor_key]).decode('ascii').lower()
                if neighbor_key in sys_names:
                    sysname = bytes(sys_names[neighbor_key]).decode('ascii')
                else:
                    sysname = ''
            neighbors[port] = { 'mac': mac, 'ip': None, 'sysname': sysname }

        return neighbors


LLDP_VARIANTS = VariantsSet('LLDP neighbor table retrieval', (StandardLLDP, TPLinkLLDP))

class LLDPProxy(VariantProxy):
    def __init__(self, snmp_proxy, host):
        VariantProxy.__init__(self, snmp_proxy, host, LLDP_VARIANTS)
    def get_neighbors(self):
        return self.variant.get_neighbors(self.snmp)
