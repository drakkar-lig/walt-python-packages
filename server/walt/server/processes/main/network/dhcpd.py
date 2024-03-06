import os
from collections import defaultdict
from itertools import groupby
from operator import itemgetter
from pathlib import Path

from walt.common.netsetup import NetSetup
from walt.server.processes.main.network.service import ServiceRestarter
from walt.server.tools import get_server_ip, get_walt_subnet, ip

# STATE_DIRECTORY is set by systemd to the daemon's state directory.  By
# default, it is /var/lib/walt
DHCPD_CONF_FILE = (
    Path(os.getenv("STATE_DIRECTORY", "/var/lib/walt"))
    / "services"
    / "dhcpd"
    / "dhcpd.conf"
)

CONF_PATTERN = """
#
# DO NOT EDIT THIS FILE
#
# It is automatically generated by the walt system
# and updated when needed.
#

option client-architecture code 93 = unsigned integer 16;

# global parameters
authoritative; # allow sending DHCP NAKs
next-server %(walt_server_ip)s;
option tftp-server-name "%(walt_server_ip)s";
option ntp-servers %(walt_server_ip)s;
option broadcast-address %(subnet_broadcast)s;
option domain-name "walt";
option domain-search "walt";
option domain-name-servers %(walt_server_ip)s;

# get the vendor class identifier if available
if exists vendor-class-identifier {
    set vci = option vendor-class-identifier;
} else {
    set vci = "";
}

# get the user class identifier if available
if exists user-class {
    set uci = option user-class;
} else {
    set uci = "";
}

# handle various forms of PXE booting
if (vci = "PXEClient:Arch:00000:UNDI:002001") {
    if (substring(uci, 0, 9) = "walt.node") {
        # we get here when ipxe is running its walt bootup script on the node.
        # the VCI is still the one of PXE, but the UCI as been modified to
        # indicate a walt node.
        # This script specifies itself the script to boot from TFTP, so
        # no filename is given here.
    }
    elsif ((b2a(16,8,":",substring(hardware, 1, 3)) = "28:cd:c1") or
           (b2a(16,8,":",substring(hardware, 1, 3)) = "b8:27:eb") or
           (b2a(16,8,":",substring(hardware, 1, 3)) = "d8:3a:dd") or
           (b2a(16,8,":",substring(hardware, 1, 3)) = "dc:a6:32") or
           (b2a(16,8,":",substring(hardware, 1, 3)) = "e4:5f:01")) {
        # native rpi3b+ network boot
        option vendor-class-identifier "PXEClient";
        option vendor-encapsulated-options "Raspberry Pi Boot";
    }
    elsif option client-architecture = 00:00 {
        # x86 PXE boot
        filename "pxe/walt-x86-undionly.kpxe";
    }
}

# walt unregistered devices
subnet %(subnet_ip)s netmask %(subnet_netmask)s {
    # declare ranges of unallocated addresses
%(walt_unallocated_ranges_conf)s

    # check if the ip is already used
    ping-check = 1;

    # no need to recheck often if you are now registered
    min-lease-time 6000000;
    max-lease-time 6000000;
    default-lease-time 6000000;

    # when we assign a new IP address, let walt register
    # this new device
    on commit {
        if known {  # if the device already has a host entry
            set is_known = "1";     # execute() expects string arguments
            # var dev_type was set in the relevant host entry
        }
        else {
            set is_known = "0";     # execute() expects string arguments
            set dev_type = "unknown";
        }
        # if the device type is not known (yet)
        if (dev_type = "unknown") {
            set ip_string = b2a(10, 8, ".", leased-address);
            # note: we ensure all 6 bytes of the mac address are left padded with 0 if
            # needed (b2a would not output '0e' but just 'e').
            set mac_address_string = concat (
                suffix(concat("0", b2a(16, 8, "", substring(hardware,1,1))),2), ":",
                suffix(concat("0", b2a(16, 8, "", substring(hardware,2,1))),2), ":",
                suffix(concat("0", b2a(16, 8, "", substring(hardware,3,1))),2), ":",
                suffix(concat("0", b2a(16, 8, "", substring(hardware,4,1))),2), ":",
                suffix(concat("0", b2a(16, 8, "", substring(hardware,5,1))),2), ":",
                suffix(concat("0", b2a(16, 8, "", substring(hardware,6,1))),2)
            );
            set client_name = pick-first-value(
                option host-name, config-option host-name, client-name, "");
            execute("walt-dhcp-event", "commit", vci, uci, ip_string,
                mac_address_string, client_name, is_known, dev_type);
        }
    }
}

# walt registered devices
# -----------------------

# devices with netsetup = "NAT"

group {
    option routers %(walt_server_ip)s;

    # switches

%(walt_registered_nat_switch_conf)s

    # nodes

%(walt_registered_nat_node_conf)s

    # unknown devices

%(walt_registered_nat_unknown_conf)s
}

# devices with netsetup = "LAN"

group {
    # switches

%(walt_registered_lan_switch_conf)s

    # nodes

%(walt_registered_lan_node_conf)s

    # unknown devices

%(walt_registered_lan_unknown_conf)s
}
""".replace("b2a", "binary-to-ascii")

RANGE_CONF_PATTERN = "    range %(first)s %(last)s;"

HOST_CONF_PATTERN = """\
    host %(hostname)s {
        hardware ethernet %(mac)s;
        fixed-address %(ip)s;
        option host-name "%(hostname)s";
        set dev_type = "%(type)s";
    }
"""


# see https://stackoverflow.com/a/2154437
def get_contiguous_ranges(ips):
    ips = sorted(ips)
    ranges = []
    for k, g in groupby(enumerate(ips), lambda i_x: i_x[0] - int(i_x[1])):
        group = list(map(itemgetter(1), g))
        ranges.append((group[0], group[-1]))
    return ranges


def generate_dhcpd_conf(subnet, devices):
    confs_per_category = defaultdict(list)
    for device_info in devices:
        conf = HOST_CONF_PATTERN % device_info._asdict()
        conf_category_list = confs_per_category[
            (device_info.netsetup, device_info.type)
        ]
        conf_category_list.append(conf)
    # compute free ips
    server_ip = get_server_ip()
    free_ips = set(subnet.hosts())
    free_ips.discard(ip(server_ip))
    free_ips -= set(ip(d.ip) for d in devices)
    range_confs = []
    for r in get_contiguous_ranges(free_ips):
        first, last = r
        range_confs.append(RANGE_CONF_PATTERN % dict(first=first, last=last))
    infos = dict(
        walt_server_ip=server_ip,
        subnet_ip=subnet.network_address,
        subnet_broadcast=subnet.broadcast_address,
        subnet_netmask=subnet.netmask,
        walt_unallocated_ranges_conf="\n".join(range_confs),
    )
    for netsetup, netsetup_label in ((NetSetup.LAN, "lan"), (NetSetup.NAT, "nat")):
        for dev_type in ("node", "switch", "unknown"):
            confs = confs_per_category[(netsetup, dev_type)]
            infos.update(
                {f"walt_registered_{netsetup_label}_{dev_type}_conf": "\n".join(confs)}
            )
    return CONF_PATTERN % infos


QUERY_DEVICES_WITH_IP = """
    SELECT d.mac, ip, name as hostname, type,
        COALESCE((conf->'netsetup')::int, 0) as netsetup
    FROM devices d LEFT JOIN nodes n ON d.mac = n.mac
    WHERE ip IS NOT NULL
      AND type != 'server'
      AND ip::inet << %s::cidr
    ORDER BY d.mac;
"""


class DHCPServer(object):
    def __init__(self, db, ev_loop):
        self.db = db
        self.restarter = ServiceRestarter(ev_loop, "dhcpd", "walt-server-dhcpd.service")

    def update(self, force=False, cb=None):
        subnet = get_walt_subnet()
        devices = list(self.db.execute(QUERY_DEVICES_WITH_IP, (str(subnet),)))
        conf = generate_dhcpd_conf(subnet, devices)
        old_conf = ""
        if DHCPD_CONF_FILE.exists():
            old_conf = DHCPD_CONF_FILE.read_text()
        if conf != old_conf:
            DHCPD_CONF_FILE.parent.mkdir(parents=True, exist_ok=True)
            DHCPD_CONF_FILE.write_text(conf)
            self.restarter.inc_config_version()
        if (not self.restarter.uptodate()) or force:
            self.restarter.restart(cb=cb)
        else:
            if cb is not None:
                cb()

    def wf_update(self, wf, force=False, **env):
        self.update(force=force, cb=wf.next)
