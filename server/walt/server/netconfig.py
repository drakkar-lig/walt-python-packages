import os
import os.path
import sys
import time

from walt.common.tools import do, failsafe_makedirs, get_persistent_random_mac, succeeds
from walt.server import conf

WALT_STATUS_DIR = "/var/lib/walt"
IFACE_STATE_FILE = WALT_STATUS_DIR + "/.%(iface)s.state"
IFACE_MAC_FILE = WALT_STATUS_DIR + "/.%(iface)s.mac"
DOT1Q_FILTER = """\
ebtables -t filter -A FORWARD -p 802_1Q \
    -i %(src)s -o %(dst)s -j DROP"""
WAIT_INTERFACE_DELAY = 10  # seconds


def filter_out_8021q(iface_src, iface_dst):
    do(DOT1Q_FILTER % dict(src=iface_src, dst=iface_dst))


def get_state_file(iface):
    return IFACE_STATE_FILE % dict(iface=iface)


def open_state_file(iface, mode):
    return open(get_state_file(iface), mode)


def remove_state_file(iface):
    os.remove(get_state_file(iface))


def get_mac_file(iface):
    return IFACE_MAC_FILE % dict(iface=iface)


def remove_mac_file(iface):
    os.remove(get_mac_file(iface))


def get_vlan(iface_conf):
    return iface_conf.get("vlan", None)


def get_raw_iface(iface_conf):
    return iface_conf.get("raw-device", None)


def set_iface_up(iface):
    do("ip link set up dev %s" % iface)


def create_dummy_iface(iface, state_file):
    do("ip link add %s type dummy" % iface)
    state_file.write(iface + "\n")


def create_vlan_iface(raw_iface, vlan, vlan_iface, state_file):
    do("ip link add link %s name %s type vlan id %d" % (raw_iface, vlan_iface, vlan))
    set_iface_up(vlan_iface)
    state_file.write(vlan_iface + "\n")


def create_bridge_iface(br_iface, interfaces, state_file):
    mac = get_persistent_random_mac(get_mac_file(br_iface))
    do(f"ip link add {br_iface} address {mac} type bridge")
    for iface in interfaces:
        do("ip link set dev %s master %s" % (iface, br_iface))
    set_iface_up(br_iface)
    state_file.write(br_iface + "\n")


def define_iface_altname(iface, iface_altname):
    do(f"ip link property add dev {iface} altname {iface_altname}")


def setup_ip_conf(iface, ip_conf):
    if ip_conf == "dhcp":
        do("dhclient %s" % iface)
    else:
        do("ip addr add %s dev %s" % (ip_conf, iface))


def up(iface, iface_conf):
    raw_iface = get_raw_iface(iface_conf)
    vlan = get_vlan(iface_conf)
    if raw_iface is None and vlan is not None:
        sys.exit(f'{iface} has wrong configuration: "vlan" but no "raw-device".')
    if raw_iface is not None:
        # If the machine is booting, we may be here before the network interface
        # card effectively appears.  Wait for it a little here.
        if not succeeds("ip link show dev %s" % raw_iface):
            print("Interface %s not found, waiting for it to appear…" % raw_iface)
            time.sleep(WAIT_INTERFACE_DELAY)
            if not succeeds("ip link show dev %s" % raw_iface):
                # Here, it is really an error.  Interface should exist.
                raise RuntimeError("Interface %s does not exist" % raw_iface)
    with open_state_file(iface, "w") as state_file:
        if raw_iface is None:
            # we cannot set a bridge interface up if no interface is
            # linked to it. so we create a dummy interface device to
            # fix this.
            raw_iface = f"{iface}-dummy"
            create_dummy_iface(raw_iface, state_file)
        set_iface_up(raw_iface)
        if vlan:
            vlan_iface = raw_iface + "." + str(vlan)
            create_vlan_iface(raw_iface, vlan, vlan_iface, state_file)
            base_iface = vlan_iface
        else:
            base_iface = raw_iface
        # Historically, all networks (walt-net, walt-out, ...) were
        # set on a bridge interface. Several network services we
        # provide still rely on the walt server IP set on walt-net
        # bridge.
        # For other networks (walt-adm, or custom networks such as
        # walt-out) it is better to use the underlying interface
        # (i.e., physical or vlan interface) directly and avoid
        # creating a useless bridge. Moreover, if the machine was
        # previously used for a different purpose, the mac address
        # might have been previously allowed on the network.
        # Running dhclient on a bridge instead would involve DHCP
        # messages with the mac address of the bridge, which we
        # generated randomly. So instead of creating a useless bridge,
        # we just add an alternate name to the interface.
        if iface == "walt-net":
            create_bridge_iface(iface, (base_iface,), state_file)
            # isc-dhcp-server reads packets in raw mode on its interface
            # thus it detects 8021q (VLAN-tagged) packets it should not see.
            # In order to work around this issue we do not let 8021q
            # packets cross the bridge and reach our interface.
            filter_out_8021q(base_iface, iface)
        else:
            define_iface_altname(base_iface, iface)
        if "ip" in iface_conf:
            setup_ip_conf(iface, iface_conf["ip"])


def down(iface):
    with open_state_file(iface, "r") as state_file:
        for line in state_file.readlines():
            sub_iface = line.strip()
            do("ip link del dev %s" % sub_iface)
    remove_state_file(iface)


def run():
    # Handle argument
    if len(sys.argv) < 2:
        sys.exit('Missing 1st argument: "up" or "down".')
    action = sys.argv[1]
    if action not in ("up", "down"):
        sys.exit('1st argument must be "up" or "down".')
    # Handle IFACE environment variable
    iface = os.environ.get("IFACE")
    if iface is not None:
        print(f"Using interface {iface} from environment variable IFACE.")
        try:
            iface_conf = conf["network"][iface]
        except LookupError:
            sys.exit(f"{iface}: interface is not listed in configuration file.")
        network_confs = {iface: iface_conf}
    else:
        # Activate all interfaces
        network_confs = conf["network"]
    # Do the job
    failsafe_makedirs(WALT_STATUS_DIR)
    for iface, iface_conf in network_confs.items():
        if action == "up":
            up(iface, iface_conf)
        elif action == "down":
            down(iface)


if __name__ == "__main__":
    run()
