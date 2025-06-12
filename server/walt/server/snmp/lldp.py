#!/usr/bin/env python
import functools
import numpy as np
import re

from walt.server.diskcache import DISK_CACHE
from walt.server.snmp.base import (
    Variant,
    VariantProxy,
    VariantsSet,
    decode_ipv4_address,
    decode_mac_address,
    enum_label,
)
from walt.server.snmp.mibs import load_mib, unload_mib

DT_PORT_LABELS = np.dtype([("id", int), ("label", object)])


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
            if enum_label(chassis_types[neighbor_key]) == "macAddress":
                timeMark, port, index = neighbor_key
                port = int(port)
                mac_per_port[port] = decode_mac_address(chassis_values[neighbor_key])
                if neighbor_key in sys_names:
                    sysname_per_port[port] = str(sys_names[neighbor_key])
                else:
                    sysname_per_port[port] = ""

        # retrieve ip addresses of neighbors
        for neighbor_ip_info in ip_info:
            timeMark, port, index, subtype, encoded_ip = neighbor_ip_info
            if enum_label(subtype).lower() == "ipv4":
                ip_per_port[int(port)] = decode_ipv4_address(encoded_ip)

        # merge info
        neighbors = {}
        for port, mac in mac_per_port.items():
            ip = ip_per_port[port] if port in ip_per_port else None
            sysname = sysname_per_port[port]
            neighbors[port] = {"mac": mac, "ip": ip, "sysname": sysname}

        return neighbors

    @staticmethod
    def get_port_names(snmp_proxy):
        try:
            arr = np.fromiter(snmp_proxy.lldpLocPortId.items(), DT_PORT_LABELS)
            arr["label"] = arr["label"].astype(str)
            return arr.view(np.recarray)
        except Exception:
            return None


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
        neighbors = {}

        # perform SNMP requests
        chassis_types = dict(snmp_proxy.lldpNeighborChassisIdType)
        chassis_values = dict(snmp_proxy.lldpNeighborChassisId)
        sys_names = dict(snmp_proxy.lldpNeighborDeviceName)
        port_info = dict(snmp_proxy.lldpLocalPortId)

        # retrieve mac address and sysname of neighbors
        for neighbor_key in chassis_types:
            if bytes(chassis_types[neighbor_key]) == b"MAC address":
                port_id, index = neighbor_key
                port_str = bytes(port_info[int(port_id)]).decode("ascii")
                port = int(re.split(r"[^\d]+", port_str)[-1])
                mac = bytes(chassis_values[neighbor_key]).decode("ascii").lower()
                if neighbor_key in sys_names:
                    sysname = bytes(sys_names[neighbor_key]).decode("ascii")
                else:
                    sysname = ""
            neighbors[port] = {"mac": mac, "ip": None, "sysname": sysname}

        return neighbors

    @staticmethod
    def get_port_names(snmp_proxy):
        return None  # not implemented yet


LLDP_VARIANTS = VariantsSet("LLDP neighbor table retrieval", (StandardLLDP, TPLinkLLDP))


class LLDPProxy(VariantProxy):
    def __init__(self, snmp_proxy, sw_ip):
        self._sw_ip = sw_ip
        VariantProxy.__init__(self, snmp_proxy, sw_ip, LLDP_VARIANTS)

    def get_neighbors(self):
        # if port labels are not known yet, compute them and save
        # them in disk cache
        cache_key = ("all-lldp-pl", self._sw_ip)
        partial = functools.partial(self.variant.get_port_names, self.snmp)
        DISK_CACHE.get(cache_key, partial)
        # compute neighbors
        return self.variant.get_neighbors(self.snmp)


# The following functions must be callable even if the switch does
# not support reporting LLDP data through SNMP, so we declare them
# as module functions.

def get_port_number_from_lldp_label(sw_ip, sw_port_lldp_label):
    cache_key_all = ("all-lldp-pl", sw_ip)
    info_all = DISK_CACHE.get(cache_key_all)
    if info_all is not None:
        rows = info_all[info_all.label == sw_port_lldp_label]
        if len(rows) == 1:
            return int(rows[0].id)
    cache_key_single = ("lldp-pl", sw_ip, sw_port_lldp_label)
    return DISK_CACHE.get(cache_key_single)


def save_lldp_label_for_port_number(sw_ip, sw_port, sw_port_lldp_label):
    cache_key_all = ("all-lldp-pl", sw_ip)
    if DISK_CACHE.get(cache_key_all) is not None:
        # in the meantime, we got all port labels for this switch
        # so no need to record this single port entry.
        return
    cache_key_single = ("lldp-pl", sw_ip, sw_port_lldp_label)
    DISK_CACHE.save(cache_key_single, sw_port)
