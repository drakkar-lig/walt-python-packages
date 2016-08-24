#!/usr/bin/env python
from walt.server.threads.main.snmp.base import load_mib

class IPSetupProxy(object):
    def __init__(self, snmp_proxy):
        self.snmp = snmp_proxy
        load_mib("NETGEAR-SWITCHING-MIB")

    def perform_dhcp_setup(self):
        # the switch is already configured to boot using DHCP
        # by default, but affecting this value again causes
        # the switch to restart the DHCP procedure, which is
        # exactly what we expect.
        self.snmp.agentNetworkConfigProtocol = 3 # dhcp

    def record_current_ip_config_as_static(self):
        # if server and switches are restarted, the switches may
        # send a DHCP request before the DHCP server of the WalT server
        # is started.
        # This causes the switches to choose a default address,
        # e.g. 192.168.0.239 for Netgear switches.
        # This causes major issues because several switches
        # may get this same address.
        # Thus, the first time a switch is detected with a DHCP IP belonging
        # to the WalT network, we statically set this IP in its bootup
        # procedure.
        current_ip = str(self.snmp.agentNetworkIPAddress)
        current_netmask = str(self.snmp.agentNetworkSubnetMask)
        with self.snmp as batch:
            batch.agentNetworkConfigProtocol = 1
            batch.agentNetworkIPAddress = current_ip
            batch.agentNetworkSubnetMask = current_netmask
