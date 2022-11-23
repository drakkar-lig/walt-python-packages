#!/usr/bin/env python
from collections import defaultdict
from walt.server.processes.blocking.snmp.mibs import load_mib, unload_mib
from walt.server.processes.blocking.snmp.base import decode_mac_address, enum_label, \
                                                    Variant, VariantsSet, VariantProxy

class VLANCapableBridge(Variant):
    @staticmethod
    def test_or_exception(snmp_proxy):
        dict(snmp_proxy.dot1qTpFdbPort)
        dict(snmp_proxy.dot1qTpFdbStatus)

    @staticmethod
    def load():
        load_mib(b"Q-BRIDGE-MIB")

    @staticmethod
    def unload():
        unload_mib(b"Q-BRIDGE-MIB")

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
            if enum_label(status) == 'learned':
                macs_per_port[port].add(mac)

        return macs_per_port

BRIDGE_VARIANTS = VariantsSet('Switch forwarding table retrieval', (VLANCapableBridge,))

class BridgeProxy(VariantProxy):
    def __init__(self, snmp_proxy, host):
        VariantProxy.__init__(self, snmp_proxy, host, BRIDGE_VARIANTS)
    def get_macs_per_port(self):
        return self.variant.get_macs_per_port(self.snmp)
