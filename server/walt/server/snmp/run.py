#!/usr/bin/env python
import sys

from snimpy.snmp import SNMPException
from walt.server import snmp
from walt.server.const import POE_EXIT_CODE_OTHER_DEVICE


def get_macs_on_port(sw_ip, snmp_conf, sw_port):
    """Return the MAC addresses detected on this switch port, using the
    LLDP neighbor table and the forwarding table (learned entries), as
    "walt device rescan" does: some switches only respond to one of them.
    Return None if none of these tables can be read."""
    macs, readable = set(), False
    try:
        proxy = snmp.Proxy(sw_ip, snmp_conf, lldp=True)
        neighbor = proxy.lldp.get_neighbors().get(sw_port)
        if neighbor is not None:
            macs.add(neighbor["mac"])
        readable = True
    except Exception:
        pass
    try:
        proxy = snmp.Proxy(sw_ip, snmp_conf, bridge=True)
        macs |= proxy.bridge.get_macs_per_port().get(sw_port, set())
        readable = True
    except Exception:
        pass
    return macs if readable else None


def sw_port_set_poe(sw_ip, sw_port, poe_status,
                    sw_snmp_version, sw_snmp_community, expected_mac=None):
    snmp_conf = {
        "version": sw_snmp_version,
        "community": sw_snmp_community
    }
    proxy = snmp.Proxy(sw_ip, snmp_conf)
    if not proxy.ping():
        return False, "no SNMP response"
    # before turning PoE power off, check that the expected device is
    # still connected to this switch port: the network topology recorded
    # by walt may be outdated, and the port may now power another node.
    # We refuse only if other MAC addresses are detected on the port and
    # the expected one is not: a node may show several MAC addresses on
    # its port (e.g., the one of another interface in its LLDP
    # announces). If the LLDP and forwarding tables cannot be read, or
    # if no MAC address is detected on the port, we cannot tell, so we
    # go on.
    # note: as for the topology, the port numbers of these tables are
    # the LLDP port numbers (on a bridge, they are the dot1dBasePort
    # numbers).
    if poe_status is False and expected_mac is not None:
        macs = get_macs_on_port(sw_ip, snmp_conf, sw_port) or set()
        if len(macs) > 0 and expected_mac not in macs:
            return (False,
                    "detected another device on this switch port",
                    POE_EXIT_CODE_OTHER_DEVICE)
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
Usage: {sys.argv[0]} <sw_ip> <sw_port> [on|off] <sw_snmp_version> <sw_snmp_community> [<expected_mac>]

When turning PoE off, if <expected_mac> is given, and other MAC addresses
but not this one are detected on the switch port (LLDP neighbor or
forwarding table), PoE is not turned off and the exit code is {POE_EXIT_CODE_OTHER_DEVICE}.\
"""

def walt_set_poe():
    if len(sys.argv) not in (6, 7) or sys.argv[3] not in ("on", "off"):
        print(USAGE)
        return
    try:
        sw_ip = sys.argv[1]
        sw_port = int(sys.argv[2])
        poe_status = {"on": True, "off": False}[sys.argv[3]]
        sw_snmp_version = int(sys.argv[4])
        sw_snmp_community = sys.argv[5]
        expected_mac = sys.argv[6].lower() if len(sys.argv) == 7 else None
    except Exception:
        print(USAGE)
        return
    res = sw_port_set_poe(sw_ip, sw_port, poe_status,
                          sw_snmp_version, sw_snmp_community, expected_mac)
    if res[0]:
        return
    else:
        print(res[1], file=sys.stderr)
        sys.stderr.flush()
        exit_code = res[2] if len(res) > 2 else 1
        sys.exit(exit_code)
