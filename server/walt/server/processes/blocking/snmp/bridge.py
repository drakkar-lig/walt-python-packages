#!/usr/bin/env python
from collections import defaultdict

from walt.server.processes.blocking.snmp.base import (
    Variant,
    VariantProxy,
    VariantsSet,
    decode_mac_address,
    enum_label,
)
from walt.server.processes.blocking.snmp.mibs import load_mib, unload_mib


class VLANCapableBridge(Variant):
    @staticmethod
    def test_or_exception(snmp_proxy):
        dict(snmp_proxy.dot1qTpFdbPort)
        dict(snmp_proxy.dot1qTpFdbStatus)
        dict(snmp_proxy.ifPhysAddress)
        str(snmp_proxy.dot1dBaseBridgeAddress)

    @staticmethod
    def load():
        load_mib("IF-MIB")
        load_mib("BRIDGE-MIB")
        load_mib(b"Q-BRIDGE-MIB")

    @staticmethod
    def unload():
        unload_mib(b"Q-BRIDGE-MIB")
        unload_mib(b"BRIDGE-MIB")
        unload_mib(b"IF-MIB")

    @staticmethod
    def get_macs_per_port(snmp_proxy):
        macs_per_port = defaultdict(set)

        # perform SNMP requests
        forwarding_db_ports = dict(snmp_proxy.dot1qTpFdbPort)
        forwarding_db_status = dict(snmp_proxy.dot1qTpFdbStatus)

        # parse
        for k, v in forwarding_db_ports.items():
            vlan, mac = k
            vlan = int(vlan)
            mac = decode_mac_address(mac)
            port = int(v)
            status = forwarding_db_status.get(k, None)
            if status is None:
                continue
            if enum_label(status) == "learned":
                macs_per_port[port].add(mac)

        return macs_per_port

    @staticmethod
    def get_secondary_macs(snmp_proxy):
        macs = set(dict(snmp_proxy.ifPhysAddress).values())
        macs |= set((snmp_proxy.dot1dBaseBridgeAddress,))
        macs = set(decode_mac_address(mac) for mac in macs)
        macs -= set(("00:00:00:00:00:00",))
        return macs


BRIDGE_VARIANTS = VariantsSet("Switch forwarding table retrieval", (VLANCapableBridge,))


class BridgeProxy(VariantProxy):
    def __init__(self, snmp_proxy, host):
        VariantProxy.__init__(self, snmp_proxy, host, BRIDGE_VARIANTS)

    def get_macs_per_port(self):
        return self.variant.get_macs_per_port(self.snmp)

    def get_secondary_macs(self):
        return self.variant.get_secondary_macs(self.snmp)
