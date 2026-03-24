#!/usr/bin/env python
import snimpy
from snimpy.manager import Manager
from walt.server import const
from walt.server.snmp.bridge import BridgeProxy
from walt.server.snmp.lldp import LLDPProxy
from walt.server.snmp.poe import PoEProxy
from walt.server.snmp.mibs import (
    get_loaded_mibs,
    load_mib,
)

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
    def ping(self):
        # check an SNMP attribute which is almost always implemented
        if b"SNMPv2-MIB" not in get_loaded_mibs():
            load_mib(b"SNMPv2-MIB")
        try:
            self.snmp.sysDescr
            return True
        except snimpy.snmp.SNMPException:
            return False
