#!/usr/bin/env python
from walt.server.threads.main.snmp.base import load_mib, unload_mib, get_loaded_mibs, \
                    unload_any_of_these_mibs
from snimpy import snmp

POE_PORT_ENABLED=1
POE_PORT_DISABLED=2
POE_PORT_SPEEDS=(10**7, 10**8, 10**9)   # 10Mb/s 100Mb/s 1Gb/s

# Several mibs exist depending on the device vendor.
# In the worst case, on the WalT platform we
# could find devices of several vendors.
# In this case we should unload a mib and load another
# when we pass from one vendor to another.
# In order to handle this, we use a wrapper around the
# SNMP proxy. The SafeProxy wrapper ensures that each time
# the SNMP proxy is accessed, the appropriate MIB is loaded.

CANDIDATE_POE_MIBS = ["POWER-ETHERNET-MIB", "NETGEAR-POWER-ETHERNET-MIB"]
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
    if not host in POE_PORT_MAPPING_CACHE:
        if "IF-MIB" not in get_loaded_mibs():
            load_mib("IF-MIB")
        iface_port_indexes = list(
                int(k) for k, v in snmp_proxy.ifSpeed.items()
                if v in POE_PORT_SPEEDS)
        iface_type_indexes = list(
                int(k) for k, v in snmp_proxy.ifType.items()
                if int(v) == ETHERNETCSMACD)
        poe_port_indexes = list(
                (int(grp_idx), int(grp_port)) \
                for grp_idx, grp_port in snmp_proxy.pethPsePortAdminEnable.keys())
        # check if we have the same number of poe ports and 10/100/1000 ports
        if len(iface_port_indexes) == len(poe_port_indexes):
            # this probably means we can associate iface_port_indexes and
            # poe_port_indexes one by one:
            iface_to_poe_index = { a: b for a, b in \
                    zip(iface_port_indexes, poe_port_indexes) }
        # otherwise, check if we have a linear range of ethernet ports
        # (i.e. there are no holes in those port indexes)
        elif max(a-b for a, b in \
                zip(iface_type_indexes[1:], iface_type_indexes[:-1])) == 1:
            # this probably means we can associate iface_type_indexes and
            # poe_port_indexes one by one:
            iface_to_poe_index = { a: b for a, b in \
                    zip(iface_type_indexes, poe_port_indexes) }
        else:
            raise RuntimeError(MSG_ISSUE_POE_PORT_MAPPING % host)
        POE_PORT_MAPPING_CACHE[host] = iface_to_poe_index
    return POE_PORT_MAPPING_CACHE[host]

def detect_correct_mib(snmp_proxy, host):
    unload_any_of_these_mibs(CANDIDATE_POE_MIBS)
    for mib in CANDIDATE_POE_MIBS:
        load_mib(mib)
        try:
            dummy = snmp_proxy.pethPsePortAdminEnable.keys()
            break # ok previous line passed with no error
        except (snmp.SNMPNoSuchObject,
                snmp.SNMPNoSuchInstance,
                snmp.SNMPEndOfMibView):
            # issue with this MIB, try next one
            unload_mib(mib)
            mib = None
    if mib == None:
        raise RuntimeError(
            'Device %s does not seem to handle PoE SNMP requests.' % \
                        host)
    return mib

def ensure_correct_mib(correct_mib):
    if correct_mib not in get_loaded_mibs():
        unload_any_of_these_mibs(CANDIDATE_POE_MIBS)
        load_mib(correct_mib)

class SafeProxy(object):
    def __init__(self, snmp_proxy, host):
        # avoid the modified __setattr__ (see below) to be called
        object.__setattr__(self, 'unsafe_proxy', snmp_proxy)
        object.__setattr__(self, 'selected_mib',
                        detect_correct_mib(snmp_proxy, host))

    # The following __getattr__ and __setattr__ functions
    # ensure that before accessing the SNMP proxy,
    # the PoE MIB appropriate for this device is loaded.
    def __getattr__(self, name):
        ensure_correct_mib(self.selected_mib)
        return getattr(self.unsafe_proxy, name)

    def __setattr__(self, name, value):
        ensure_correct_mib(self.selected_mib)
        self.unsafe_proxy.__setattr__(name, value)

class PoEProxy(object):

    def __init__(self, snmp_proxy, host):
        self.snmp = SafeProxy(snmp_proxy, host)
        self.port_mapping = get_poe_port_mapping(snmp_proxy, host)

    def set_port(self, switch_port, active_or_not):
        port_state = POE_PORT_ENABLED if active_or_not else POE_PORT_DISABLED
        poe_port = self.port_mapping[switch_port]
        self.snmp.pethPsePortAdminEnable[poe_port] = port_state

