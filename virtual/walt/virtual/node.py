#!/usr/bin/env python
import sys, subprocess, time, random, platform
from contextlib import contextmanager
from walt.common.apilink import ServerAPILink
from walt.virtual.fakeipxe import ipxe_boot
from walt.virtual.udhcpc import udhcpc_fake_netboot
from plumbum import cli

OS_ENCODING = sys.stdout.encoding
HOST_CPU = platform.machine()

# the following values have been selected from output of
# qemu-system-<host-cpu> -machine help
if HOST_CPU == 'x86_64':
    QEMU_MACHINE    = 'pc'
    QEMU_PRODUCT    = 'Standard PC (i440FX + PIIX, 1996)'
    QEMU_CPU        = 'host'
    QEMU_NET_DRIVER = 'virtio-net-pci'
elif HOST_CPU == 'aarch64':
    QEMU_MACHINE    = 'virt-3.1'
    QEMU_PRODUCT    = 'QEMU 3.1 ARM Virtual Machine'
    QEMU_CPU        = 'host,aarch64=off'   # we use 32-bits mode
    QEMU_NET_DRIVER = 'virtio-net-device'
else:
    raise Exception('Unknown host CPU: ' + HOST_CPU)

MANUFACTURER = "QEMU"
QEMU_PROG = "qemu-system-" + HOST_CPU
QEMU_RAM = 512
QEMU_CORES = 4
QEMU_ARGS = QEMU_PROG + " \
                -enable-kvm \
                -machine " + QEMU_MACHINE + "\
                -cpu " + QEMU_CPU + "\
                -m " + str(QEMU_RAM) + "\
                -name %(name)s \
                -smp " + str(QEMU_CORES) + "\
                -nographic \
                -netdev bridge,br=walt-net,id=mynet \
                -device " + QEMU_NET_DRIVER + ",mac=%(mac)s,netdev=mynet \
                -serial mon:stdio \
                -no-reboot"

"""
qemu-system-aarch64 -enable-kvm -m 512 -nographic -machine virt -cpu host,aarch64=off -kernel kernel -append "$bootargs" -netdev bridge,br=walt-net,id=mynet -device virtio-net-device,mac=${ethaddr},netdev=mynet -smp 4 -no-reboot -device nec-usb-xhci,id=xhci \
           -device usb-host,hostbus=1,hostport=1.2 \
           -device usb-host,hostbus=1,hostport=1.3 \
           -device usb-host,hostbus=1,hostport=1.4 \
           -device usb-host,hostbus=1,hostport=1.5
"""


USAGE = """\
Usage: %(prog)s --mac <node_mac> --ip <node_ip> --model <node_model> --hostname <node_name> --server-ip <server_ip>
       %(prog)s --net-conf-udhcpc --mac <node_mac> --model <node_model>\
"""

def get_env_start(info):
    if info._udhcpc:
        required_args = ('mac', 'model')
    else:
        required_args =  ('mac', 'ip', 'model', 'hostname', 'server_ip')
    env = { attr: getattr(info, '_' + attr, None) for attr in required_args }
    if None in env.values():
        print(USAGE % dict(prog = sys.argv[0]))
        sys.exit()
    if info._udhcpc:
        env['fake-network-setup'] = udhcpc_fake_netboot
    else:
        env['fake-network-setup'] = api_fake_netboot
    env.update({
        "manufacturer": MANUFACTURER,
        "product": QEMU_PRODUCT,
        "qemu-args": ' '.join(QEMU_ARGS.split())
    })
    return env

@contextmanager
def api_fake_netboot(env):
    send_register_request(env)
    add_network_info(env)
    yield True
    # nothing to release when leaving the context, in this case

def send_register_request(env):
    with ServerAPILink(env['server_ip'], 'VSAPI') as server:
        vci = 'walt.node.' + env['model']
        return server.register_device(vci, '', env['ip'], env['mac'])

def add_network_info(env):
    with ServerAPILink(env['server_ip'], 'VSAPI') as server:
        info = server.get_device_info(env['mac'])
        print(info)
        if info is None:
            return False
        env.update(netmask=info['netmask'], gateway=info['gateway'])

def random_wait():
    delay = int(random.random()*10) + 1
    while delay > 0:
        print('waiting for %ds' % delay)
        time.sleep(1)
        delay -= 1

def node_loop(info):
    random.seed()
    try:
        while True:
            # wait randomly to mitigate simultaneous load of various
            # virtual nodes
            random_wait()
            print("Starting...")
            env = get_env_start(info)
            ipxe_boot(env)
    except NotImplementedError as e:
        print((str(e)))
        time.sleep(120)

class WalTVirtualNode(cli.Application):
    _udhcpc = False     # default

    """run a virtual node"""
    def main(self):
        node_loop(self)

    @cli.switch("--mac", str)
    def mac(self, mac_address):
        """specify node's mac address"""
        self._mac = mac_address

    @cli.switch("--model", str)
    def model(self, model):
        """specify node's model"""
        self._model = model

    @cli.switch("--ip", str)
    def ip(self, ip):
        """specify node's ip"""
        self._ip = ip

    @cli.switch("--server-ip", str)
    def server_ip(self, server_ip):
        """specify walt server ip"""
        self._server_ip = server_ip

    @cli.switch("--hostname", str)
    def hostname(self, hostname):
        """specify node's hostname"""
        self._hostname = hostname

    @cli.switch("--net-conf-udhcpc")
    def set_net_conf_udhcpc(self):
        """use udhcpc to get network parameters"""
        self._udhcpc = True

def run():
    WalTVirtualNode.run()
