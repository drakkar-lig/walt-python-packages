#!/usr/bin/env python
from base import load_mib, unload_mib, get_loaded_mibs, \
                    unload_any_of_these_mibs

POE_PORT_ENABLED=1
POE_PORT_DISABLED=2

# Several mibs exist depending on the device vendor.
# In the worst case, on the WalT platform we
# could find devices of several vendors. 
# In this case we should unload a mib and load another
# when we pass from one vendor to another.
# In order to handle this, we use a wrapper around the
# SNMP proxy. This wrapper ensures that each time the SNMP
# proxy is accessed, the appropriate MIB is loaded.

CANDIDATE_POE_MIBS = ["POWER-ETHERNET-MIB", "NETGEAR-POWER-ETHERNET-MIB"]

def detect_correct_mib(snmp_proxy, host):
    unload_any_of_these_mibs(CANDIDATE_POE_MIBS)
    for mib in CANDIDATE_POE_MIBS:
        load_mib(mib)
        try:
            dummy = snmp_proxy.pethPsePortAdminEnable.keys()
            break # ok previous line passed with no error
        except:
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

    def set_port(self, switch_port, active_or_not):
        port_state = POE_PORT_ENABLED if active_or_not else POE_PORT_DISABLED
        self.snmp.pethPsePortAdminEnable[(1,switch_port)] = port_state

