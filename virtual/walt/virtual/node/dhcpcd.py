import shlex
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from subprocess import run

from walt.virtual.node.udhcpc import temporary_network_pipe

BRIDGE_INTF = "walt-net"


def dhcpcd_get_vars(env, interface):
    env['hostname'] = "virt-pamtos"
    env['ip'] = "192.168.172.97"
    env['server_ip'] = "192.168.172.1"
    env['gateway'] = "192.168.172.1"
    env['netmask'] = "255.255.252.1"


def dhcpcd_setup_interface(env, interface):
    run(shlex.split(f"dhcpcd -i {env['vci']} -1 -n {interface}"), check=True)


@contextmanager
def dhcpcd_fake_netboot(env):
    bridge_dev_dir = Path('/sys/class/net') / BRIDGE_INTF
    while not bridge_dev_dir.is_dir():
        print("'%s' not available yet. Will retry in a moment." % BRIDGE_INTF)
        time.sleep(3)
    with temporary_network_pipe() as pipe:
        run(shlex.split(f"ip link set dev {pipe[0]} master {BRIDGE_INTF} up"), check=True)
        run(shlex.split(f"ip link set dev {pipe[1]} address {env['mac']} up"), check=True)
        try:
            # we need to save env variables retrieved through DHCP
            # (they are needed to interpret ipxe scripts)
            dhcpcd_get_vars(env, pipe[1])
            # we also need to setup the interface to handle TFTP transfers
            dhcpcd_setup_interface(env, pipe[1])
            yield True
        except:
            traceback.print_exc()
            yield False
