import os
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from collections import defaultdict

from walt.server.processes.main.network.netsetup import NetSetup
from walt.server.tools import ip, get_walt_subnet, get_server_ip, get_dns_servers

# STATE_DIRECTORY is set by systemd to the daemon's state directory.  By
# default, it is /var/lib/walt
DHCPD_CONF_FILE = Path(os.getenv("STATE_DIRECTORY", "/var/lib/walt")) / \
                    'services' / 'dhcpd' / 'dhcpd.conf'

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
    elsif ((binary-to-ascii(16,8,":",substring(hardware, 1, 3)) = "b8:27:eb") or
           (binary-to-ascii(16,8,":",substring(hardware, 1, 3)) = "28:cd:c1") or
           (binary-to-ascii(16,8,":",substring(hardware, 1, 3)) = "dc:a6:32") or
           (binary-to-ascii(16,8,":",substring(hardware, 1, 3)) = "e4:5f:01")) {
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
        set ip_string = binary-to-ascii(10, 8, ".", leased-address);
        # note: we ensure all 6 bytes of the mac address are left padded with 0 if needed
        # (binary-to-ascii would not output '0e' but just 'e').
        set mac_address_string = concat (
            suffix (concat ("0", binary-to-ascii (16, 8, "", substring(hardware,1,1))),2), ":",
            suffix (concat ("0", binary-to-ascii (16, 8, "", substring(hardware,2,1))),2), ":",
            suffix (concat ("0", binary-to-ascii (16, 8, "", substring(hardware,3,1))),2), ":",
            suffix (concat ("0", binary-to-ascii (16, 8, "", substring(hardware,4,1))),2), ":",
            suffix (concat ("0", binary-to-ascii (16, 8, "", substring(hardware,5,1))),2), ":",
            suffix (concat ("0", binary-to-ascii (16, 8, "", substring(hardware,6,1))),2)
        );
        set client_name = pick-first-value(option host-name, config-option host-name, client-name, "");
        execute("walt-dhcp-event", "commit", vci, uci,
                        ip_string, mac_address_string, client_name);
    }
}

# walt registered devices
# -----------------------

# devices with netsetup = "NAT"

group {
    option routers %(walt_server_ip)s;
    option domain-name-servers %(dns_servers)s;

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
"""

RANGE_CONF_PATTERN = "    range %(first)s %(last)s;"

HOST_CONF_PATTERN = """\
    host %(hostname)s {
        hardware ethernet %(mac)s;
        fixed-address %(ip)s;
        option host-name "%(hostname)s";
    }
"""

# see http://stackoverflow.com/questions/2154249/identify-groups-of-continuous-numbers-in-a-list
def get_contiguous_ranges(ips):
    ips = sorted(ips)
    ranges=[]
    for k, g in groupby(enumerate(ips), lambda i_x:i_x[0]-int(i_x[1])):
        group = list(map(itemgetter(1), g))
        ranges.append((group[0], group[-1]))
    return ranges

def generate_dhcpd_conf(subnet, devices):
    confs_per_category = defaultdict(list)
    free_ips = set(subnet.hosts())
    server_ip = get_server_ip()
    free_ips.discard(ip(server_ip))
    for device_info in devices:
        conf = HOST_CONF_PATTERN % device_info
        conf_category_list = confs_per_category[(device_info['netsetup'], device_info['type'])]
        conf_category_list.append(conf)
        if device_info['ip'] in free_ips:
            free_ips.discard(device_info['ip'])
    range_confs = []
    for r in get_contiguous_ranges(free_ips):
        first, last = r
        range_confs.append(
            RANGE_CONF_PATTERN % dict(
                    first=first,
                    last=last
        ))
    infos = dict(
        walt_server_ip=server_ip,
        subnet_ip=subnet.network_address,
        subnet_broadcast=subnet.broadcast_address,
        subnet_netmask=subnet.netmask,
        dns_servers=", ".join(map(str, get_dns_servers())),
        walt_unallocated_ranges_conf='\n'.join(range_confs)
    )
    for netsetup, netsetup_label in ((NetSetup.LAN, 'lan'), (NetSetup.NAT, 'nat')):
        for dev_type in ('node', 'switch', 'unknown'):
            confs = confs_per_category[(netsetup, dev_type)]
            infos.update({
                f'walt_registered_{netsetup_label}_{dev_type}_conf': '\n'.join(confs)
            })
    return CONF_PATTERN % infos

QUERY_DEVICES_WITH_IP="""
    SELECT devices.mac, ip, name, type, COALESCE((conf->'netsetup')::int, 0) as netsetup
    FROM devices LEFT JOIN nodes ON devices.mac = nodes.mac
    WHERE ip IS NOT NULL ORDER BY devices.mac;
"""

# Restarting the DHCP service can be requested quite often when a large set of
# new nodes are being registered.
# To be lighter, we ensure only one restart command is running at a time.
# When the restart command completes, we check if the config was updated again
# in the meanwhile; if yes, we loop again.

class DHCPServer(object):
    def __init__(self, db, ev_loop):
        self.db = db
        self.ev_loop = ev_loop
        self.service_version = 0
        self.config_version = 0
        self.restarting = False
    def update(self, force=False):
        subnet = get_walt_subnet()
        devices = []
        for item in self.db.execute(QUERY_DEVICES_WITH_IP):
            device_ip = ip(item.ip)
            if device_ip not in subnet:
                continue
            if item.type != 'server':
                devices.append(dict(
                    type=item.type,
                    hostname=item.name,
                    ip=device_ip,
                    mac=item.mac,
                    netsetup=item.netsetup))
        conf = generate_dhcpd_conf(subnet, devices)
        old_conf = ""
        if DHCPD_CONF_FILE.exists():
            old_conf = DHCPD_CONF_FILE.read_text()
        if conf != old_conf:
            DHCPD_CONF_FILE.parent.mkdir(parents=True, exist_ok=True)
            DHCPD_CONF_FILE.write_text(conf)
            force = True # perform the restart below
        if force == True:
            self.config_version += 1
            if not self.restarting:
                self.restarting = True
                self.restart_service_loop()
            print('dhcpd conf updated.')
    def restart_service_loop(self):
        if self.config_version == self.service_version:
            # ok done
            self.restarting = False
            return
        else:
            next_service_version = self.config_version
            print('dhcpd updating to version', next_service_version)
            def callback():
                self.service_version = next_service_version
                self.restart_service_loop()
            self.ev_loop.do('systemctl reload-or-restart walt-server-dhcpd.service', callback)
