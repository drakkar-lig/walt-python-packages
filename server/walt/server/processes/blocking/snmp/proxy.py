#!/usr/bin/env python
from snimpy.manager import Manager
from walt.server import const
from walt.server.processes.blocking.snmp.bridge import BridgeProxy
from walt.server.processes.blocking.snmp.lldp import LLDPProxy
from walt.server.processes.blocking.snmp.poe import PoEProxy

SNMP_OPTS = {"retries": 2, "timeout": const.SNMP_TIMEOUT, "cache": True}


class Proxy(object):
    def __init__(self, host, snmp_conf, poe=False, lldp=False, bridge=False):
        opts = SNMP_OPTS.copy()
        opts.update(host=host)
        opts.update(snmp_conf)
        self.host = host
        self.snmp = Manager(**opts)
        if poe:
            self.poe = PoEProxy(self.snmp, host)
        if lldp:
            self.lldp = LLDPProxy(self.snmp, host)
        if bridge:
            self.bridge = BridgeProxy(self.snmp, host)
