#!/usr/bin/env python
from base import load_mib

class DHCPProxy(object):
    def __init__(self, snmp_proxy):
        self.snmp = snmp_proxy
        load_mib("NETGEAR-SWITCHING-MIB")

    def restart(self):
        # the switch is already configured to boot using DHCP
        # by default, but affecting this value again causes
        # the switch to restart the DHCP procedure, which is
        # exactly what we expect.
        self.snmp.agentNetworkConfigProtocol = 3 # dhcp

