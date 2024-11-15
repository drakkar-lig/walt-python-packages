#!/usr/bin/env python
import functools

from collections import defaultdict
from walt.server.diskcache import DISK_CACHE
from walt.server.snmp.base import Variant, VariantProxy, VariantsSet
from walt.server.snmp.mibs import (
    get_loaded_mibs,
    load_mib,
    unload_mib,
)

POE_PORT_ENABLED = 1
POE_PORT_DISABLED = 2
POE_PORT_SPEEDS = (10**7, 10**8, 10**9)  # 10Mb/s 100Mb/s 1Gb/s

POE_PORT_MAPPING_CACHE = {}

# In POWER-ETHERNET-MIB, PoE ports are identified using a
# tuple (grp_index, port_index).
# grp_index identifies a PoE port group (box in the stack,
# module in a rack, etc. or 1 for non-modular devices).
# port_index identifies the PoE port within this group.
# On the other hand, LLDP ports are identified using a global
# index meaningful for the whole switch.
# When we want to alter PoE state on a port, we have to compute
# the appropriate (grp_index, port_index) given the LLDP port index.
# The following solution works on our stacked switches:
# - list the switch ports with speed 10Mb/s 100Mb/s or 1Gb/s
#   (these are the possible speeds for a PoE port), using IF-MIB
# - list the PoE ports, using POWER-ETHERNET-MIB
# - verify that these 2 lists have the same length
# - "zip" these 2 lists in order to attach each LLDP port to its
#   corresponding PoE port identification tuple.
# On netgear 8-port switches, this fails because unconnected ports
# return a speed of 0 (and some other interfaces too (fiber, vlans)).
# In this case, we check if the list of ports with type
# 'ethernet CSMA/CD' is a continuous range. In this case,
# we can probably consider the PoE ports are enumerated
# the same way. IMPORTANT: This only works with switches where the
# PoE capable ports are listed first.

MSG_ISSUE_POE_PORT_MAPPING = """\
WalT could not guess how to correlate PoE ports and LLDP ports
on switch %s. Sorry."""

ETHERNETCSMACD = 6


def get_poe_port_mapping(snmp_proxy, host):
    if host not in POE_PORT_MAPPING_CACHE:
        if b"IF-MIB" not in get_loaded_mibs():
            load_mib(b"IF-MIB")
        iface_port_indexes = list(
            int(k) for k, v in snmp_proxy.ifSpeed.items() if v in POE_PORT_SPEEDS
        )
        iface_type_indexes = list(
            int(k) for k, v in snmp_proxy.ifType.items() if int(v) == ETHERNETCSMACD
        )
        poe_port_indexes = list(
            (int(grp_idx), int(grp_port))
            for grp_idx, grp_port in snmp_proxy.pethPsePortAdminEnable.keys()
        )
        iface_to_poe_index = None
        # check if we have the same number of poe ports and 10/100/1000 ports
        if len(iface_port_indexes) == len(poe_port_indexes):
            # this probably means we can associate iface_port_indexes and
            # poe_port_indexes one by one:
            iface_to_poe_index = {
                a: b for a, b in zip(iface_port_indexes, poe_port_indexes)
            }
        # otherwise, check if we have a linear range of ethernet ports
        # (i.e. there are no holes in those port indexes)
        if iface_to_poe_index is None and (
            max(a - b for a, b in zip(iface_type_indexes[1:], iface_type_indexes[:-1]))
            == 1
        ):
            # this probably means we can associate iface_type_indexes and
            # poe_port_indexes one by one:
            iface_to_poe_index = {
                a: b for a, b in zip(iface_type_indexes, poe_port_indexes)
            }
        # otherwise, we observe the holes in the range of interfaces and
        # try to see if we can map each poe group to a continuous sub-range
        # of interfaces
        if iface_to_poe_index is None:
            poe_ports_per_group = defaultdict(list)
            for grp_idx, grp_port in poe_port_indexes:
                poe_ports_per_group[grp_idx].append(grp_port)
            poe_group_lengths = set(len(grp_ports)
                                    for grp_ports in poe_ports_per_group.values())
            # check all poe groups have the same number of ports
            if len(poe_group_lengths) == 1:
                poe_group_len = list(poe_group_lengths)[0]
                # there is probably a jump in interface numbers between each group
                holes = (0,) + tuple(c+1 for a, b, c in zip(
                                iface_port_indexes[:-1],
                                iface_port_indexes[1:],
                                range(len(iface_port_indexes))) if b-a > 1)
                iface_to_poe_index = {}
                poe_idx = 0
                hole_idx = 0
                failed = False
                while poe_idx < len(poe_port_indexes):
                    poe_range = poe_port_indexes[ poe_idx :
                                                  poe_idx + poe_group_len ]
                    while True:
                        if hole_idx >= len(holes):
                            failed = True
                            break
                        iface_idx = holes[hole_idx]
                        hole_idx += 1
                        if iface_idx + poe_group_len > len(iface_port_indexes):
                            failed = True
                            break
                        iface_range = iface_port_indexes[ iface_idx :
                                                          iface_idx + poe_group_len ]
                        # check iface_range is contiguous
                        if iface_range[-1] - iface_range[0] + 1 == poe_group_len:
                            # ok
                            iface_to_poe_index.update({
                                a: b for a, b in zip(iface_range, poe_range)
                            })
                            break
                        # otherwise try next hole
                    if failed:
                        break
                    else:
                        poe_idx += poe_group_len
                if failed:
                    iface_to_poe_index = None
        # otherwise, sorry, no more ideas...
        if iface_to_poe_index is None:
            raise RuntimeError(MSG_ISSUE_POE_PORT_MAPPING % host)
        POE_PORT_MAPPING_CACHE[host] = iface_to_poe_index
    return POE_PORT_MAPPING_CACHE[host]


class StandardPoE(Variant):
    @classmethod
    def test_or_exception(cls, snmp_proxy):
        list(snmp_proxy.pethPsePortAdminEnable.keys())

    @classmethod
    def load(cls):
        load_mib(b"POWER-ETHERNET-MIB")

    @classmethod
    def unload(cls):
        unload_mib(b"POWER-ETHERNET-MIB")

    @classmethod
    def check_poe_enabled(cls, snmp_proxy, port_mapping, switch_port):
        poe_port = port_mapping[switch_port]
        return int(snmp_proxy.pethPsePortAdminEnable[poe_port]) == POE_PORT_ENABLED

    @classmethod
    def set_port(cls, snmp_proxy, port_mapping, switch_port, active_or_not):
        port_state = POE_PORT_ENABLED if active_or_not else POE_PORT_DISABLED
        poe_port = port_mapping[switch_port]
        snmp_proxy.pethPsePortAdminEnable[poe_port] = port_state

    @classmethod
    def check_poe_in_use(cls, snmp_proxy, port_mapping, switch_port):
        poe_port = port_mapping[switch_port]
        # value 3 means 'deliveringPower'
        return int(snmp_proxy.pethPsePortDetectionStatus[poe_port]) == 3

    @classmethod
    def get_poe_port_mapping(cls, snmp_proxy, host):
        return get_poe_port_mapping(snmp_proxy, host)


# Netgear variant is the same as standard one except that the loaded MIB is not the same
class NetgearPoE(StandardPoE):
    @classmethod
    def load(cls):
        load_mib(b"NETGEAR-POWER-ETHERNET-MIB")

    @classmethod
    def unload(cls):
        unload_mib(b"NETGEAR-POWER-ETHERNET-MIB")


# TP-link variant (not standard)
class TPLinkPoE(Variant):
    @classmethod
    def test_or_exception(cls, snmp_proxy):
        dict(snmp_proxy.tpPoePortStatus)

    @classmethod
    def load(cls):
        load_mib(b"TPLINK-MIB")
        load_mib(b"TPLINK-POWER-OVER-ETHERNET-MIB")

    @classmethod
    def unload(cls):
        unload_mib(b"TPLINK-POWER-OVER-ETHERNET-MIB")
        unload_mib(b"TPLINK-MIB")

    @classmethod
    def check_poe_enabled(cls, snmp_proxy, port_mapping, switch_port):
        poe_port = port_mapping[switch_port]
        return int(snmp_proxy.tpPoePortStatus[poe_port]) == 1

    @classmethod
    def set_port(cls, snmp_proxy, port_mapping, switch_port, active_or_not):
        port_state = 1 if active_or_not else 0
        poe_port = port_mapping[switch_port]
        snmp_proxy.tpPoePortStatus[poe_port] = port_state

    @classmethod
    def check_poe_in_use(cls, snmp_proxy, port_mapping, switch_port):
        poe_port = port_mapping[switch_port]
        return int(snmp_proxy.tpPoePowerStatus[poe_port]) == 2  # 'on'

    @classmethod
    def get_poe_port_mapping(cls, snmp_proxy, host):
        return {int(k): int(k) for k in dict(snmp_proxy.tpPoePortStatus).keys()}


# TP-link should be first, otherwise sending invalid requests when probing other
# variants seem to cause it to temporarily stop answering all requests (DoS mitigation?)
POE_VARIANTS = VariantsSet("PoE SNMP requests", (TPLinkPoE, StandardPoE, NetgearPoE))


class PoEProxy(VariantProxy):
    def __init__(self, snmp_proxy, host):
        VariantProxy.__init__(self, snmp_proxy, host, POE_VARIANTS)
        cache_key = ("poe-port-mapping", host)
        partial = functools.partial(self.variant.get_poe_port_mapping, snmp_proxy, host)
        self.port_mapping = DISK_CACHE.get(cache_key, partial)

    def check_poe_enabled(self, switch_port):
        return self.variant.check_poe_enabled(self.snmp, self.port_mapping, switch_port)

    def set_port(self, switch_port, active_or_not):
        self.variant.set_port(self.snmp, self.port_mapping, switch_port, active_or_not)

    def check_poe_in_use(self, switch_port):
        return self.variant.check_poe_in_use(self.snmp, self.port_mapping, switch_port)
