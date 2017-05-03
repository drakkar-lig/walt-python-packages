#!/usr/bin/env python
from snimpy.manager import Manager
from walt.server.threads.main.snmp.poe import PoEProxy
from walt.server.threads.main.snmp.lldp import LLDPProxy
from walt.server.threads.main.snmp.vlan import VlanProxy
from walt.server.threads.main.snmp.ipsetup import IPSetupProxy
from walt.server import const

SNMP_OPTS = {
    'retries': 2,
    'timeout': const.SNMP_TIMEOUT,
    'cache': True
}

class Proxy(object):
        def __init__(self, host, snmp_conf, poe=False, lldp=False, vlan=False, ipsetup=False):
            opts = SNMP_OPTS.copy()
            opts.update(host = host)
            opts.update(snmp_conf)
            self.host = host
            self.snmp = Manager(**opts)
            if poe:
                self.poe = PoEProxy(self.snmp, host)
            if lldp:
                self.lldp = LLDPProxy(self.snmp)
            if vlan:
                self.vlan = VlanProxy(self.snmp)
            if ipsetup:
                self.ipsetup = IPSetupProxy(self.snmp)

