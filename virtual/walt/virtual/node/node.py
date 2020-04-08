#!/usr/bin/env python
import sys, subprocess, time, random, platform, re
from contextlib import contextmanager
from walt.common.apilink import ServerAPILink
from walt.common.logs import LoggedApplication
from walt.virtual.node.fakeipxe import ipxe_boot
from walt.virtual.node.udhcpc import udhcpc_fake_netboot
from plumbum import cli
from pathlib import Path

OS_ENCODING = sys.stdout.encoding
HOST_CPU = platform.machine()

# the following values have been selected from output of
# qemu-system-<host-cpu> -machine help
if HOST_CPU == 'x86_64':
    QEMU_MACHINE_DEF = '-machine pc -cpu host'
    QEMU_PRODUCT     = 'Standard PC (i440FX + PIIX, 1996)'
    QEMU_NET_DRIVER  = 'virtio-net-pci'
elif HOST_CPU == 'aarch64':
    QEMU_MACHINE_DEF = '-machine virt-3.1 -machine highmem=off -cpu host,aarch64=off' # we use 32-bits mode
    QEMU_PRODUCT     = 'QEMU 3.1 ARM Virtual Machine'
    QEMU_NET_DRIVER  = 'virtio-net-device'
else:
    raise Exception('Unknown host CPU: ' + HOST_CPU)

MANUFACTURER = "QEMU"
QEMU_PROG = "qemu-system-" + HOST_CPU
DEFAULT_QEMU_RAM = 512
DEFAULT_QEMU_CORES = 4
QEMU_ARGS = QEMU_PROG + " \
                -enable-kvm " + \
                QEMU_MACHINE_DEF + "\
                -m %(ram)d \
                -smp %(cpu_cores)d \
                -name %(name)s \
                -nographic \
                -netdev bridge,br=walt-net,id=mynet \
                -device " + QEMU_NET_DRIVER + ",mac=%(mac)s,netdev=mynet \
                -serial mon:stdio \
                -no-reboot"

def get_qemu_usb_args():
    model_file = Path('/proc/device-tree/model')
    if not model_file.exists():
        raise Exception('Do not know how to map USB ports on this host device (no /proc/device-tree/model file).')
    model = model_file.read_text()
    if model.startswith('Raspberry Pi 3 Model B Plus'):
        usb_ports = (
            ('1', '1.1.2'),  # upper left
            ('1', '1.1.3'),  # lower left
            ('1', '1.3'),    # upper right
            ('1', '1.2')     # lower right
        )
    elif model.startswith('Raspberry Pi 3 Model B'):
        raise Exception('TODO')
    else:
        raise Exception('Do not know how to map USB ports on this host device (%s).' % model)
    usb_args = '-device nec-usb-xhci,id=xhci '
    usb_args += ' '.join(('-device usb-host,hostbus=%s,hostport=%s' % t) for t in usb_ports)
    return usb_args

USAGE = """\
Usage: %(prog)s [--attach-usb] --mac <node_mac> --ip <node_ip> --model <node_model> --hostname <node_name> --server-ip <server_ip>
       %(prog)s [--attach-usb] --net-conf-udhcpc --mac <node_mac> --model <node_model>\
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
    env['cpu_cores'] = info._cpu_cores
    env['ram'] = info._ram
    if info._udhcpc:
        env['fake-network-setup'] = udhcpc_fake_netboot
    else:
        env['fake-network-setup'] = api_fake_netboot
    qemu_args = QEMU_ARGS
    if info._attach_usb:
        qemu_args += ' ' + get_qemu_usb_args()
    env.update({
        "manufacturer": MANUFACTURER,
        "product": QEMU_PRODUCT,
        "qemu-args": ' '.join(qemu_args.split()),
        "vci": 'walt.node.' + env['model']
    })
    if info._reboot_command is not None:
        env['reboot-command'] = info._reboot_command
    return env

@contextmanager
def api_fake_netboot(env):
    send_register_request(env)
    add_network_info(env)
    yield True
    # nothing to release when leaving the context, in this case

def send_register_request(env):
    with ServerAPILink(env['server_ip'], 'VSAPI') as server:
        return server.register_device(env['vci'], '', env['ip'], env['mac'])

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

class WalTVirtualNode(LoggedApplication):
    _udhcpc = False         # default
    _attach_usb = False     # default
    _reboot_command = None  # default
    _cpu_cores = DEFAULT_QEMU_CORES
    _ram = DEFAULT_QEMU_RAM

    """run a virtual node"""
    def main(self):
        self.init_logs()
        node_loop(self)

    @cli.switch("--attach-usb")
    def set_attach_usb(self):
        """attach host USB ports to virtual node"""
        self._attach_usb = True

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

    @cli.switch("--cpu-cores", int)
    def set_cpu_cores(self, cpu_cores):
        """specify node's number of cpu cores"""
        self._cpu_cores = cpu_cores

    @cli.switch("--ram", str)
    def set_ram(self, ram):
        """specify node's ram amount (e.g. 512M or 1G)"""
        if re.match(r'\d+[MG]', ram) is None:
            raise ValueError('Invalid RAM amount specified (should be for instance 512M or 1G).')
        # convert to megabytes
        ram_megabytes = int(ram[:-1])
        if ram[-1] == 'G':
            ram_megabytes *= 1024
        self._ram = ram_megabytes

    @cli.switch("--net-conf-udhcpc")
    def set_net_conf_udhcpc(self):
        """use udhcpc to get network parameters"""
        self._udhcpc = True

    @cli.switch("--on-vm-reboot", str)
    def set_reboot_command(self, shell_command):
        """define a command to be called if virtual machine reboots"""
        self._reboot_command = shell_command

def run():
    WalTVirtualNode.run()
