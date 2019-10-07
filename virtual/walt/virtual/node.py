#!/usr/bin/env python
import sys, subprocess, time, random
from walt.common.apilink import ServerAPILink
from walt.virtual.fakeipxe import ipxe_boot
from plumbum import cli

OS_ENCODING = sys.stdout.encoding
MANUFACTURER = "QEMU"
KVM_RAM = 512
KVM_CORES = 4
KVM_ARGS = "kvm -m " + str(KVM_RAM) + "\
                -name %(name)s \
                -smp " + str(KVM_CORES) + "\
                -display none \
                -net nic,macaddr=%(mac)s,model=virtio \
                -net bridge,br=walt-net \
                -serial mon:stdio \
                -no-reboot"

USAGE = """\
Usage: %(prog)s --mac <node_mac> --ip <node_ip> --model <node_model> --hostname <node_name> --server-ip <server_ip>\
"""

def get_qemu_product_name():
    line = subprocess.check_output('kvm -machine help | grep default', shell=True).decode(OS_ENCODING)
    line = line.replace('(default)', '')
    return line.split(' ', 1)[1].strip()

def get_env_start(info):
    args = tuple(getattr(info, attr, None) for attr in ('_mac', '_ip', '_model', '_hostname', '_server_ip'))
    if None in args:
        print(USAGE % dict(prog = sys.argv[0]))
        sys.exit()
    mac, ip, model, name, server_ip = args
    return {
        "mac": mac,
        "ip": ip,
        "model": model,
        "name": name,
        "hostname": name,
        "mac:hexhyp": mac.replace(":","-"),
        "manufacturer": MANUFACTURER,
        "product": get_qemu_product_name(),
        "next-server": server_ip,
        "kvm-args": ' '.join(KVM_ARGS.split())
    }

def send_register_request(env):
    with ServerAPILink(env['next-server'], 'VSAPI') as server:
        vci = 'walt.node.' + env['model']
        return server.register_device(vci, '', env['ip'], env['mac'])

def add_network_info(env):
    with ServerAPILink(env['next-server'], 'VSAPI') as server:
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
            send_register_request(env)
            add_network_info(env)
            ipxe_boot(env)
    except NotImplementedError as e:
        print((str(e)))
        time.sleep(120)

class WalTVirtualNode(cli.Application):
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

def run():
    WalTVirtualNode.run()
