#!/usr/bin/env python
import sys, subprocess, time, random, platform, re, atexit, signal, shlex, shutil
from os import getpid, getenv, truncate
from contextlib import contextmanager
from walt.common.apilink import ServerAPILink
from walt.common.logs import LoggedApplication
from walt.common.fakeipxe import ipxe_boot
from walt.common.tools import failsafe_makedirs
from walt.virtual.node.udhcpc import udhcpc_fake_netboot
from plumbum import cli
from pathlib import Path

OS_ENCODING = sys.stdout.encoding
HOST_CPU = platform.machine()
VNODE_DEFAULT_PID_PATH = '/var/lib/walt/nodes/%(mac)s/pid'
VNODE_DEFAULT_SCREEN_SESSION_PATH = '/var/lib/walt/nodes/%(mac)s/screen_session'
VNODE_DEFAULT_DISKS_PATH = '/var/lib/walt/nodes/%(mac)s/disks'
VNODE_IFUP_SCRIPT = shutil.which('walt-vnode-ifup')
VNODE_IFDOWN_SCRIPT = shutil.which('walt-vnode-ifdown')

# the following values have been selected from output of
# qemu-system-<host-cpu> -machine help
if HOST_CPU == 'x86_64':
    QEMU_MACHINE_DEF = '-machine pc -cpu host'
    QEMU_PRODUCT     = 'Standard PC (i440FX + PIIX, 1996)'
    QEMU_APPEND      = ''
    QEMU_NET_DRIVER  = 'virtio-net-pci'
elif HOST_CPU == 'aarch64':
    # notes:
    # * the following allows to boot a 64-bit guest kernel, while still maintaining the
    #   possiblity for the userspace to be either 32-bit (thus compatible with raspbian
    #   based walt images) or 64-bit.
    # * old definition for 32-bits mode kernel only (i.e. walt.node.qemu-arm-32) was:
    #   QEMU_MACHINE_DEF = '-machine virt-6.0 -machine highmem=off -cpu host,aarch64=off'
    # * "sysctl.abi.cp15_barrier=2 sysctl.abi.setend=2" allow to let these obsolete ARM
    #   instructions be run by the CPU with no emulation nor warnings (they are in use
    #   by some 32-bit arm programs)
    QEMU_MACHINE_DEF = '-machine virt-6.0 -cpu host'
    QEMU_PRODUCT     = 'QEMU 6.0 ARM Virtual Machine'
    QEMU_APPEND      = 'sysctl.abi.cp15_barrier=2 sysctl.abi.setend=2'
    QEMU_NET_DRIVER  = 'virtio-net-device'
else:
    raise Exception('Unknown host CPU: ' + HOST_CPU)

MANUFACTURER = "QEMU"
QEMU_PROG = "qemu-system-" + HOST_CPU
DEFAULT_QEMU_RAM = 512
DEFAULT_QEMU_CORES = 4
DEFAULT_QEMU_DISKS = ()
QEMU_ARGS = QEMU_PROG + " \
                -enable-kvm " + \
                QEMU_MACHINE_DEF + "\
                -m %(ram)d \
                -smp %(cpu-cores)d \
                %(disks)s \
                -name %(name)s \
                -nographic \
                -netdev type=tap,id=mynet,vhost=on," + \
                       "script=" + VNODE_IFUP_SCRIPT + ",downscript=" + VNODE_IFDOWN_SCRIPT + " \
                -device " + QEMU_NET_DRIVER + ",mac=%(mac)s,netdev=mynet \
                -serial mon:stdio \
                -no-reboot \
                -kernel %(boot-kernel)s"

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

def get_qemu_disks(info):
    if len(info._disks) == 0:
        return ""
    if info._disks_path is None:
        disks_path = VNODE_DEFAULT_DISKS_PATH  % dict(mac = info._mac)
    else:
        disks_path = info._disks_path
    Path(disks_path).mkdir(parents=True, exist_ok=True)
    qemu_disk_opts = ''
    for disk_index, disk_cap in enumerate(info._disks):
        disk_cap_bytes = disk_cap * 1000000000
        disk_path = Path(f'{disks_path}/disk_{disk_index}.dd')
        if disk_path.exists():
            # if not expected size, remove it
            if disk_path.stat().st_size != disk_cap_bytes:
                disk_path.unlink()
        if not disk_path.exists():
            disk_path.touch()
            truncate(str(disk_path), disk_cap_bytes)
        qemu_disk_opts += f' -drive file={disk_path},format=raw'
    return qemu_disk_opts

def get_env_start(info):
    # define initial env variables for ipxe_boot()
    if info._udhcpc:
        required_args = ('mac', 'model')
    else:
        required_args =  ('mac', 'ip', 'model', 'hostname', 'server_ip')
    env = { attr: getattr(info, '_' + attr, None) for attr in required_args }
    if None in env.values():
        print(USAGE % dict(prog = sys.argv[0]))
        sys.exit()
    env.update({
        "manufacturer": MANUFACTURER,
        "product": QEMU_PRODUCT,
        "vci": 'walt.node.' + env['model']
    })
    # define callbacks for ipxe_boot()
    if info._udhcpc:
        env['fake-network-setup'] = udhcpc_fake_netboot
    else:
        env['fake-network-setup'] = api_fake_netboot
    env['boot-function'] = boot_kvm
    # the following data is not necessary for ipxe_boot() function
    # but will be used when launching the boot-function boot_kvm()
    env['cpu-cores'] = info._cpu_cores
    env['ram'] = info._ram
    env['disks'] = get_qemu_disks(info)
    env['attach-usb'] = info._attach_usb
    env['reboot-command'] = info._reboot_command
    return env

def boot_kvm(env):
    qemu_args = QEMU_ARGS
    if env['attach-usb']:
        qemu_args += ' ' + get_qemu_usb_args()
    if 'boot-initrd' in env:
        qemu_args += ' -initrd %(boot-initrd)s'
    env['boot-kernel-cmdline'] = env.get('boot-kernel-cmdline', '') + ' ' + \
                                 QEMU_APPEND
    if len(env['boot-kernel-cmdline'].strip()) > 0:
        qemu_args += " -append '%(boot-kernel-cmdline)s'"
    cmd = qemu_args % env
    print(' '.join(cmd.split()))  # print with multiple spaces shrinked
    subprocess.call(shlex.split(cmd))
    if env['reboot-command'] is not None:
        subprocess.call(env['reboot-command'], shell=True)

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

def save_pid(info):
    pid_path = info._pid_path
    if pid_path is None:
        pid_path = VNODE_DEFAULT_PID_PATH % dict(mac = info._mac)
    pid_path = Path(pid_path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("%d\n" % getpid())

def save_screen_session(info):
    path = info._screen_session_path
    if path is None:
        path = VNODE_DEFAULT_SCREEN_SESSION_PATH % dict(mac = info._mac)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # screen passes the session name as env variable STY
    path.write_text("%s\n" % getenv('STY'))

def node_loop(info):
    random.seed()
    save_pid(info)
    save_screen_session(info)
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
    _pid_path = None        # default
    _screen_session_path = None  # default
    _disks_path = None      # default
    _cpu_cores = DEFAULT_QEMU_CORES
    _ram = DEFAULT_QEMU_RAM
    _disks = DEFAULT_QEMU_DISKS

    """run a virtual node"""
    def main(self):
        self.init_logs()
        node_loop(self)

    @cli.switch("--pid-path", str)
    def set_pid_path(self, pid_path):
        """Set pid file path"""
        self._pid_path = pid_path

    @cli.switch("--screen-session-path", str)
    def set_screen_session_path(self, screen_session_path):
        """Set screen session file path"""
        self._screen_session_path = screen_session_path

    @cli.switch("--disks-path", str)
    def set_disks_path(self, disks_path):
        """Set path where to save virtual node disk files"""
        self._disks_path = disks_path

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
        if re.match(r'^\d+[MG]$', ram) is None:
            raise ValueError('Invalid RAM amount specified (should be for instance 512M or 1G).')
        # convert to megabytes
        ram_megabytes = int(ram[:-1])
        if ram[-1] == 'G':
            ram_megabytes *= 1024
        self._ram = ram_megabytes

    @cli.switch("--disks", str)
    def set_disks(self, disks):
        """specify node's disks (e.g. none, 8G or "1T,32G")"""
        if disks != "none" and re.match(r'^\d+[GT](,\d+[GT])*$', disks) is None:
            raise ValueError('Invalid value for --disks (should be for instance none, 8G or "1T,32G").')
        # convert to gigabytes
        self._disks = []
        if disks != 'none':
            for capacity in disks.split(','):
                cap_gigabytes = int(capacity[:-1])
                if capacity[-1] == 'T':
                    cap_gigabytes *= 1000
                self._disks.append(cap_gigabytes)

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
