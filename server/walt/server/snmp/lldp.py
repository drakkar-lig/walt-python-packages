#!/usr/bin/env python
from base import load_mib, decode_ipv4_address, \
                    decode_mac_address, enum_label

class LLDPProxy(object):
    def __init__(self, snmp_proxy):
        self.snmp = snmp_proxy
        load_mib("LLDP-MIB")

    def get_neighbors(self):

        mac_per_port = {}
        ip_per_port = {}

        # perform SNMP requests
        try:
            chassis_types = dict(self.snmp.lldpRemChassisIdSubtype)
            chassis_values = dict(self.snmp.lldpRemChassisId)
            ip_info = set(self.snmp.lldpRemManAddrIfSubtype)
        except Exception:
            return {}

        # retrieve mac addresses of neighbors
        for neighbor_key in chassis_types:
            if enum_label(chassis_types[neighbor_key]) == 'macAddress':
                timeMark, port, index = neighbor_key
                mac_per_port[int(port)] = decode_mac_address(
                                chassis_values[neighbor_key])

        # retrieve ip addresses of neighbors
        for neighbor_ip_info in ip_info:
            timeMark, port, index, subtype, encoded_ip = neighbor_ip_info
            if enum_label(subtype).lower() == 'ipv4':
                ip_per_port[int(port)] = decode_ipv4_address(encoded_ip)

        # merge info
        neighbors = {}
        for port, mac in mac_per_port.items():
            ip = ip_per_port[port] if port in ip_per_port else None
            neighbors[port] = { 'mac': mac, 'ip': ip }

        return neighbors

    def get_local_ips(self):
        ips = []
        ip_info = set(self.snmp.lldpLocManAddrIfSubtype)
        for subtype, encoded_ip in ip_info:
            if enum_label(subtype).lower() == 'ipv4':
                ips.append(decode_ipv4_address(encoded_ip))
        return ips

