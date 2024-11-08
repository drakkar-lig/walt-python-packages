#!/usr/bin/env python
import sys

from snimpy.snmp import SNMPException
from walt.server import snmp


def sw_port_set_poe(sw_ip, sw_port, poe_status,
                    sw_snmp_version, sw_snmp_community):
    snmp_conf = {
        "version": sw_snmp_version,
        "community": sw_snmp_community
    }
    try:
        proxy = snmp.Proxy(sw_ip, snmp_conf, poe=True)
        # before trying to turn PoE power off, check if this switch port
        # is actually delivering power (the node may be connected to a
        # PoE capable switch, but powered by an alternate source).
        if poe_status is False:
            if     (proxy.poe.check_poe_enabled(sw_port) and not
                    proxy.poe.check_poe_in_use(sw_port)):
                return False, "node seems not PoE-powered"
        # turn poe power on or off
        proxy.poe.set_port(sw_port, poe_status)
        # confirm success to caller
        return (True,)
    except SNMPException:
        return False, "SNMP issue"
    except Exception as e:
        return False, e.__class__.__name__


USAGE=f"""\
Usage: {sys.argv[0]} <sw_ip> <sw_port> [on|off] <sw_snmp_version> <sw_snmp_community>\
"""

def walt_set_poe():
    if len(sys.argv) != 6 or sys.argv[3] not in ("on", "off"):
        print(USAGE)
        return
    try:
        sw_ip = sys.argv[1]
        sw_port = int(sys.argv[2])
        poe_status = {"on": True, "off": False}[sys.argv[3]]
        sw_snmp_version = int(sys.argv[4])
        sw_snmp_community = sys.argv[5]
    except Exception:
        print(USAGE)
        return
    res = sw_port_set_poe(sw_ip, sw_port, poe_status,
                          sw_snmp_version, sw_snmp_community)
    if res[0]:
        return
    else:
        print(res[1], file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
