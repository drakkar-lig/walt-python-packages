#!/usr/bin/env python
import atexit
import json
import os
import platform
import random
import re
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import base64
from contextlib import contextmanager
from os import getenv, getpid, truncate
from pathlib import Path

from pkg_resources import resource_string
from plumbum import cli
from walt.common.apilink import ServerAPILink
from walt.common.fakeipxe import ipxe_boot
from walt.common.logs import LoggedApplication
from walt.common.settings import parse_vnode_disks_value, parse_vnode_networks_value
from walt.common.tools import get_persistent_random_mac, interrupt_print
from walt.virtual.node.udhcpc import udhcpc_fake_netboot

OS_ENCODING = sys.stdout.encoding
HOST_CPU = platform.machine()
VNODE_DEFAULT_PID_PATH = "/var/lib/walt/nodes/%(mac)s/pid"
VNODE_DEFAULT_SCREEN_SESSION_PATH = "/var/lib/walt/nodes/%(mac)s/screen_session"
VNODE_DEFAULT_DISKS_PATH = "/var/lib/walt/nodes/%(mac)s/disks"
VNODE_DEFAULT_NETWORKS_PATH = "/var/lib/walt/nodes/%(mac)s/networks"
VNODE_IFUP_SCRIPT_TEMPLATE = resource_string(__name__, "walt-vnode-ifup").decode(
    "utf-8"
)
VNODE_IFDOWN_SCRIPT_TEMPLATE = resource_string(__name__, "walt-vnode-ifdown").decode(
    "utf-8"
)

# the following values have been selected from output of
# qemu-system-<host-cpu> -machine help
if HOST_CPU == "x86_64":
    QEMU_MACHINE_DEF = "-machine pc -cpu host"
    QEMU_PRODUCT = "Standard PC (i440FX + PIIX, 1996)"
    QEMU_APPEND = ""
    QEMU_NET_DRIVER = "virtio-net-pci"
elif HOST_CPU == "aarch64":
    # notes:
    # * the following allows to boot a 64-bit guest kernel, while still maintaining the
    #   possiblity for the userspace to be either 32-bit (thus compatible with raspbian
    #   based walt images) or 64-bit.
    # * old definition for 32-bits mode kernel only (i.e. walt.node.qemu-arm-32) was:
    #   QEMU_MACHINE_DEF = '''-machine virt-6.0 -machine highmem=off
    #                         -cpu host,aarch64=off'''
    # * "sysctl.abi.cp15_barrier=2 sysctl.abi.setend=2" allow to let these obsolete ARM
    #   instructions be run by the CPU with no emulation nor warnings (they are in use
    #   by some 32-bit arm programs)
    QEMU_MACHINE_DEF = "-machine virt-6.0 -cpu host"
    QEMU_PRODUCT = "QEMU 6.0 ARM Virtual Machine"
    QEMU_APPEND = "sysctl.abi.cp15_barrier=2 sysctl.abi.setend=2"
    QEMU_NET_DRIVER = "virtio-net-device"
else:
    raise Exception("Unknown host CPU: " + HOST_CPU)

MANUFACTURER = "QEMU"
QEMU_PROG = "qemu-system-" + HOST_CPU
DEFAULT_QEMU_RAM = 512
DEFAULT_QEMU_CORES = 4
DEFAULT_QEMU_DISKS = ()
DEFAULT_QEMU_NETWORKS = {"walt-net": {}}
DEFAULT_BOOT_DELAY = "random"
QEMU_ARGS = (
    f"{QEMU_PROG} -name %(name)s "
    f"            -enable-kvm -nodefaults {QEMU_MACHINE_DEF}"
    "             -m %(ram_megabytes)d -smp %(cpu_cores)s"
    "             %(qemu_disks_args)s %(qemu_networks_args)s"
    "             -name %(name)s -nographic -serial mon:stdio -no-reboot"
    "             -kernel %(boot_kernel)s"
)
STATE = dict(QEMU_PID=None, STOPPING=False)
STDOUT_BUFFERING_TIME = 0.05


# This script is usually called from a terminal in raw mode,
# so replace '\n' with '\r\n' for end of lines, and flush
# after each write.
class StdStreamWrapper:
    def __init__(self, stream):
        self.stream = stream

    def write(self, buf):
        self.stream.write(buf.replace("\n", "\r\n"))
        self.stream.flush()

    def flush(self):
        pass

    def fileno(self):
        return self.stream.fileno()


sys.stdout = StdStreamWrapper(sys.stdout)
sys.stderr = StdStreamWrapper(sys.stderr)


def get_qemu_usb_args():
    model_file = Path("/proc/device-tree/model")
    if not model_file.exists():
        raise Exception(
            "Do not know how to map USB ports on this host device"
            " (no /proc/device-tree/model file)."
        )
    model = model_file.read_text()
    if model.startswith("Raspberry Pi 3 Model B Plus"):
        usb_ports = (
            ("1", "1.1.2"),  # upper left
            ("1", "1.1.3"),  # lower left
            ("1", "1.3"),  # upper right
            ("1", "1.2"),  # lower right
        )
    elif model.startswith("Raspberry Pi 3 Model B"):
        raise Exception("TODO")
    else:
        raise Exception(
            "Do not know how to map USB ports on this host device (%s)." % model
        )
    usb_args = "-device nec-usb-xhci,id=xhci "
    usb_args += " ".join(
        ("-device usb-host,hostbus=%s,hostport=%s" % t) for t in usb_ports
    )
    return usb_args


USAGE = """\
Usage: %(prog)s [--attach-usb] [--managed] --mac <node_mac> --ip <node_ip>\
 --model <node_model> --hostname <node_name> --server-ip <server_ip>
       %(prog)s [--attach-usb] [--managed] --net-conf-udhcpc --mac <node_mac>\
 --model <node_model>\
"""


def apply_disk_template(disk_path, disk_template):
    if disk_template == "none":
        return  # nothing to do
    elif disk_template == "fat32":
        part_type = "0c"    # "W95 FAT32 (LBA)"
        mkfs = "mkfs.vfat -S 512"
        init_content = None
    elif disk_template == "ext4":
        part_type = "83"    # "Linux"
        mkfs = "mkfs.ext4"
        init_content = None
    elif disk_template in ("hybrid-boot-v", "hybrid-boot-p"):
        part_type = "83"    # "Linux"
        init_content = tempfile.TemporaryDirectory()
        walt_hybrid_dir = Path(f"{init_content.name}/walt_hybrid")
        walt_hybrid_dir.mkdir()
        if disk_template == "hybrid-boot-p":
            (walt_hybrid_dir / ".persistent").touch()
        mkfs = f"mkfs.ext4 -d {init_content.name}"
    # format the disk
    sfdisk_cmd = f"sfdisk --no-reread --no-tell-kernel {disk_path}"
    subprocess.run(shlex.split(sfdisk_cmd),
                   text=True,
                   input=f" 1 : start=2048 type={part_type}")
    # get a free loop device
    loop_device = subprocess.run(shlex.split("losetup -f"),
                                 capture_output=True,
                                 text=True).stdout
    # map the loop device on first partition
    subprocess.run(shlex.split(
        f"losetup -o {2048*512} {loop_device} {disk_path}"))
    # format the partition
    subprocess.run(shlex.split(
        f"{mkfs} {loop_device}"))
    # release the loop device
    subprocess.run(shlex.split(
        f"losetup -d {loop_device}"))
    # cleanup
    if init_content is not None:
        init_content.cleanup()


def get_qemu_disks_args(disks_path, disks_info):
    if len(disks_info) == 0:
        return ""
    Path(disks_path).mkdir(parents=True, exist_ok=True)
    qemu_disk_opts = ""
    for disk_index, disk_info in enumerate(disks_info):
        disk_cap, disk_template = disk_info
        disk_cap_bytes = disk_cap * 1000000000
        disk_path = Path(f"{disks_path}/disk_{disk_index}.dd")
        disk_params_file = Path(f"{disks_path}/disk_{disk_index}.info")
        if disk_params_file.exists():
            disk_params = json.loads(disk_params_file.read_text())
            old_disk_template = disk_params['template']
        else:   # backward compatibility
            old_disk_template = 'none'
        if disk_path.exists():
            # if not expected size or template, remove it
            if disk_path.stat().st_size != disk_cap_bytes or \
                    old_disk_template != disk_template:
                disk_path.unlink()
                if disk_params_file.exists():
                    disk_params_file.unlink()
        if not disk_path.exists():
            disk_path.touch()
            truncate(str(disk_path), disk_cap_bytes)
            apply_disk_template(disk_path, disk_template)
            disk_params_file.write_text(json.dumps({"template": disk_template}))
        qemu_disk_opts += (
            f" -drive file={disk_path},format=raw,id=disk{disk_index},if=none" +
            " -device virtio-scsi-pci" +
            f" -device scsi-hd,drive=disk{disk_index},product=QEMU-DISK")
    return qemu_disk_opts


def get_qemu_networks_args(hostmac, hostid, networks_path, networks_info):
    Path(networks_path).mkdir(parents=True, exist_ok=True)
    qemu_networks_opts = ""
    for network_name, network_restrictions in networks_info.items():
        ifup_script = Path(networks_path) / f"{network_name}-ifup.sh"
        ifdown_script = Path(networks_path) / f"{network_name}-ifdown.sh"
        intf_alias = f"tap to {network_name} of {hostid}"
        if "lat_us" not in network_restrictions:
            network_restrictions["lat_us"] = ""
        if "bw_Mbps" not in network_restrictions:
            network_restrictions["bw_Mbps"] = ""
        for path, template in (
            (ifup_script, VNODE_IFUP_SCRIPT_TEMPLATE),
            (ifdown_script, VNODE_IFDOWN_SCRIPT_TEMPLATE),
        ):
            path.write_text(
                template
                % dict(
                    network_name=network_name,
                    intf_alias=intf_alias,
                    **network_restrictions,
                )
            )
            path.chmod(0o755)
        if network_name == "walt-net":
            mac = hostmac
        else:
            mac_file = Path(networks_path) / f"{network_name}.mac"
            mac = get_persistent_random_mac(mac_file)
        netdev_opts = (
            f"type=tap,id={network_name},vhost=on,"
            + f"script={ifup_script},downscript={ifdown_script}"
        )
        device_opts = f"{QEMU_NET_DRIVER},mac={mac},netdev={network_name}"
        qemu_networks_opts += f" -netdev {netdev_opts} -device {device_opts}"
    return qemu_networks_opts


class VMParameters:
    def __init__(self):
        self._other_params = {}

    # allow dict-like attribute management for compatibility with
    # existing fakeipxe code of walt-common module.
    # invalid chars in the name are replaced by underscores.

    def _escape(self, attr):
        return attr.replace('-', '_').replace(':', "__")

    def __getitem__(self, attr):
        return getattr(self, self._escape(attr))

    def __setitem__(self, attr, value):
        return setattr(self, self._escape(attr), value)

    def update(self, d):
        for k, v in d.items():
            self[k] = v

    def get(self, attr, default=None):
        return getattr(self, self._escape(attr), default)

    def __contains__(self, attr):
        return hasattr(self, self._escape(attr))

    # Handle parameters requiring special processing as properties

    @property
    def ram(self):
        return self._ram

    @ram.setter
    def ram(self, ram_value):
        if re.match(r"^\d+[MG]$", ram_value) is None:
            raise ValueError(
                "Invalid RAM amount specified (should be for instance 512M or 1G)."
            )
        # convert to megabytes
        self.ram_megabytes = int(ram_value[:-1])
        if ram_value[-1] == "G":
            self.ram_megabytes *= 1024
        self._ram = ram_value

    @property
    def disks(self):
        return self._disks

    @disks.setter
    def disks(self, disks_value):
        parsing = parse_vnode_disks_value(disks_value)
        if parsing[0] is False:
            raise ValueError(f"Invalid value for disks: {parsing[1]}")
        self._disks_info = parsing[1]
        self._disks = disks_value

    @property
    def qemu_disks_args(self):
        return get_qemu_disks_args(
            self.disks_path, self._disks_info)

    @property
    def networks(self):
        return self._networks

    @networks.setter
    def networks(self, networks_value):
        parsing = parse_vnode_networks_value(networks_value)
        if parsing[0] is False:
            raise ValueError(f"Invalid value for networks: {parsing[1]}")
        self._networks_info = parsing[1]
        self._networks = networks_value

    @property
    def qemu_networks_args(self):
        return get_qemu_networks_args(
            self.mac, self.hostid, self.networks_path, self._networks_info)

    @property
    def boot_delay(self):
        return self._boot_delay

    @boot_delay.setter
    def boot_delay(self, delay_value):
        if delay_value != "random":
            try:
                delay_value = int(delay_value)
            except ValueError:
                raise ValueError(
                        'Invalid value for --boot-delay (use int value or "random")')
            if delay_value < 0:
                raise ValueError(
                        "Invalid value for --boot-delay (use a positive value)")
        self._boot_delay = delay_value


def get_env_start(info):
    # define initial env variables for ipxe_boot()
    if info._udhcpc:
        required_args = ("mac", "model")
    else:
        required_args = ("mac", "ip", "model", "hostname", "server_ip")
    env = VMParameters()
    for attr in required_args:
        value = getattr(info, "_" + attr, None)
        if value is None:
            print(USAGE % dict(prog=sys.argv[0]))
            sys.exit()
        setattr(env, attr, value)
    env.manufacturer = MANUFACTURER
    env.product = QEMU_PRODUCT
    env.vci = "walt.node." + env.model
    if info._disks_path is None:
        env.disks_path = VNODE_DEFAULT_DISKS_PATH % dict(mac=info._mac)
    else:
        env.disks_path = info._disks_path
    if info._networks_path is None:
        env.networks_path = VNODE_DEFAULT_NETWORKS_PATH % dict(mac=info._mac)
    else:
        env.networks_path = info._networks_path
    if info._hostname is None:
        env.hostid = info._mac
    else:
        env.hostid = info._hostname
    # define callbacks for ipxe_boot()
    if info._udhcpc:
        env.fake_network_setup = udhcpc_fake_netboot
    else:
        env.fake_network_setup = api_fake_netboot
    env.boot_function = boot_kvm
    # the following data is not necessary for ipxe_boot() function
    # but will be used when launching the boot-function boot_kvm()
    env.cpu_cores = info._cpu_cores
    env.ram = info._ram
    env.disks = info._disks
    env.networks = info._networks
    env.boot_delay = info._boot_delay
    env.attach_usb = info._attach_usb
    env.reboot_command = info._reboot_command
    env.managed = info._managed
    env.netmask = info._netmask
    env.gateway = info._gateway
    if info._managed:
        env.waiter = select.poll()
        env.waiter.register(0, select.POLLIN)   # listen on stdin
        env.stdin_buffer = b''
    return env


def boot_kvm(env):
    if env.managed:
        boot_kvm_managed(env)
    else:
        boot_kvm_unmanaged(env)


def get_vm_args(env):
    """Managed mode: receive commands on stdin and control VM accordingly"""
    qemu_args = QEMU_ARGS
    if env.attach_usb:
        qemu_args += " " + get_qemu_usb_args()
    if "boot-initrd" in env:
        qemu_args += " -initrd %(boot-initrd)s"
    env.boot_kernel_cmdline = (
            getattr(env, "boot_kernel_cmdline", "") + " " + QEMU_APPEND)
    if len(env.boot_kernel_cmdline.strip()) > 0:
        qemu_args += " -append '%(boot_kernel_cmdline)s'"
    cmd = qemu_args % env
    args = shlex.split(cmd)
    print(shlex.join(args))  # print with multiple spaces shrinked
    return args


def boot_kvm_managed(env):
    qemu_pid_fd = None
    # start the VM
    args = get_vm_args(env)
    qemu_stdin_r, qemu_stdin_w = os.pipe()
    qemu_stdout_r, qemu_stdout_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        # child
        os.dup2(qemu_stdin_r, 0)  # set stdin
        os.dup2(qemu_stdout_w, 1) # set stdout
        os.dup2(1, 2)  # duplicate stdout on stderr
        # cleanup file descriptors
        for fd in qemu_stdin_r, qemu_stdin_w, qemu_stdout_r, qemu_stdout_w:
            os.close(fd)
        # the qemu process should not automatically receive signals
        # targetting its parent process, thus we run it in a different
        # session
        os.setsid()
        os.execlp(args[0], *args)
    # parent
    STATE["QEMU_PID"] = pid
    # cleanup unused file descriptors
    for fd in qemu_stdin_r, qemu_stdout_w:
        os.close(fd)
    # open qemu_pid_fd
    qemu_pid_fd = os.pidfd_open(pid)
    # add qemu_pid_fd and qemu_stdout_r to the waiter
    env.waiter.register(qemu_pid_fd, select.POLLIN)
    env.waiter.register(qemu_stdout_r, select.POLLIN)
    while not STATE["STOPPING"]:
        events = env.waiter.poll(500)  # unit: milliseconds
        for fd, event in events:
            if fd == 0:
                env.stdin_buffer += os.read(0, 256)
            elif qemu_stdout_r is not None and fd == qemu_stdout_r:
                # we bufferize a little to avoid logging many small
                # vnode console chunks
                time.sleep(STDOUT_BUFFERING_TIME)
                chunk = os.read(qemu_stdout_r, 4096)
                if len(chunk) == 0:  # empty read
                    env.waiter.unregister(qemu_stdout_r)
                    os.close(qemu_stdout_r)
                    qemu_stdout_r = None
                else:
                    os.write(1, chunk)
            elif qemu_pid_fd is not None and fd == qemu_pid_fd:
                # qemu process has ended
                env.waiter.unregister(qemu_pid_fd)
                os.waitpid(STATE["QEMU_PID"], 0)
                os.close(qemu_stdin_w)
                os.close(qemu_pid_fd)
                qemu_stdin_w = None
                qemu_pid_fd = None
                STATE["QEMU_PID"] = None
                if env.reboot_command is not None:
                    subprocess.call(env.reboot_command, shell=True)
        while b'\n' in env.stdin_buffer:
            line, env.stdin_buffer = env.stdin_buffer.split(b'\n', maxsplit=1)
            line = line.decode(sys.stdin.encoding)
            args = line.split()
            if len(args) == 0:
                continue    # empty line, ignore
            if args[0] == "CONF":
                setattr(env, args[1], args[2])
            elif args[0] == "INPUT":
                if qemu_stdin_w is not None:
                    input_bytes = base64.b64decode(args[1])
                    os.write(qemu_stdin_w, input_bytes)
            elif args[0] == "KILL_VM":
                kill_vm()
            elif args[0] == "EXIT":
                STATE["STOPPING"] = True
                break
            else:
                print(f"Invalid command, ignored: {line}")
                continue
        if STATE["QEMU_PID"] is None:
            return


def boot_kvm_unmanaged(env):
    """Unmanaged mode: start the VM with static conf parameters"""
    args = get_vm_args(env)
    pid = os.fork()
    if pid == 0:
        # child
        os.dup2(STATE["SAVED_STDIN"], 0)  # restore stdin
        os.close(STATE["SAVED_STDIN"])
        os.dup2(1, 2)  # duplicate stdout on stderr
        # the qemu process should not automatically receive signals targetting
        # its parent process, thus we run it in a different session
        os.setsid()
        os.execlp(args[0], *args)
    else:
        # parent
        STATE["QEMU_PID"] = pid
        # wait until the child ends
        pid, exit_status = os.waitpid(STATE["QEMU_PID"], 0)
        STATE["QEMU_PID"] = None
    if env.reboot_command is not None:
        subprocess.call(env.reboot_command, shell=True)


@contextmanager
def api_fake_netboot(env):
    # if this program is managed by walt-server-daemon, then
    # we know the walt server already has all the information
    # about this node, so we bypass registration
    if not env.managed:
        send_register_request(env)
    if env.netmask is None or env.gateway is None:
        add_network_info(env)
    yield True
    # nothing to release when leaving the context, in this case


def send_register_request(env):
    with ServerAPILink(env.server_ip, "VSAPI") as server:
        return server.register_device(env.vci, "", env.ip, env.mac)


def add_network_info(env):
    with ServerAPILink(env.server_ip, "VSAPI") as server:
        info = server.get_device_info(env.mac)
        print(info)
        if info is None:
            return False
        if env.netmask is None:
            env.netmask = info["netmask"]
        if env.gateway is None:
            env.gateway = info["gateway"]


def random_wait():
    delay = int(random.random() * 10) + 1
    while delay > 0:
        print("waiting for %ds" % delay)
        time.sleep(1)
        delay -= 1


def save_pid(info):
    pid_path = info._pid_path
    if pid_path is None:
        pid_path = VNODE_DEFAULT_PID_PATH % dict(mac=info._mac)
    pid_path = Path(pid_path)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("%d\n" % getpid())


def save_screen_session(info):
    path = info._screen_session_path
    if path is None:
        path = VNODE_DEFAULT_SCREEN_SESSION_PATH % dict(mac=info._mac)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # screen passes the session name as env variable STY
    path.write_text("%s\n" % getenv("STY"))


def node_loop(info):
    random.seed()
    save_pid(info)
    save_screen_session(info)
    env = get_env_start(info)
    while not STATE["STOPPING"]:
        try:
            if env.boot_delay == "random":
                # default is to wait randomly to mitigate
                # simultaneous load of various virtual nodes
                random_wait()
            elif env.boot_delay > 0:
                time.sleep(env.boot_delay)
            print("Starting...")
            ipxe_boot(env)
        except Exception:
            print("Exception in node_loop()")
            import traceback
            traceback.print_exc()
            time.sleep(2)


class WalTVirtualNode(LoggedApplication):
    _udhcpc = False  # default
    _attach_usb = False  # default
    _reboot_command = None  # default
    _pid_path = None  # default
    _screen_session_path = None  # default
    _disks_path = None  # default
    _networks_path = None  # default
    _hostname = None  # default
    _cpu_cores = DEFAULT_QEMU_CORES
    _ram = DEFAULT_QEMU_RAM
    _disks = DEFAULT_QEMU_DISKS
    _networks = DEFAULT_QEMU_NETWORKS
    _boot_delay = DEFAULT_BOOT_DELAY
    _netmask = None
    _gateway = None
    _managed = False

    """run a virtual node"""

    def main(self):
        if not self._managed:
            # stdin will be used by qemu, not by us
            STATE["SAVED_STDIN"] = os.dup(0)
            os.close(0)
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

    @cli.switch("--networks-path", str)
    def set_networks_path(self, networks_path):
        """Set path where to save network-related virtual node files"""
        self._networks_path = networks_path

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

    @cli.switch("--netmask", str)
    def netmask(self, netmask):
        """specify node's netmask"""
        self._netmask = netmask

    @cli.switch("--gateway", str)
    def gateway(self, gateway):
        """specify node's gateway"""
        self._gateway = gateway

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
        self._ram = ram

    @cli.switch("--disks", str)
    def set_disks(self, disks):
        """specify node's disks (e.g. none, 8G or "1T[template=ext4],32G")"""
        self._disks = disks

    @cli.switch("--networks", str)
    def set_networks(self, networks):
        """specify node's networks (e.g. "walt-net,home-net[lat=8ms,bw=100Mbps]")"""
        self._networks = networks

    @cli.switch("--net-conf-udhcpc")
    def set_net_conf_udhcpc(self):
        """use udhcpc to get network parameters"""
        self._udhcpc = True

    @cli.switch("--on-vm-reboot", str)
    def set_reboot_command(self, shell_command):
        """define a command to be called if virtual machine reboots"""
        self._reboot_command = shell_command

    @cli.switch("--boot-delay", str)
    def set_boot_delay(self, delay):
        """define a delay before the VM [re]boots (number of seconds or "random")"""
        self._boot_delay = delay

    @cli.switch("--managed")
    def set_managed(self):
        """use STDIN to get conf and commands"""
        self._managed = True


def kill_vm():
    if STATE["QEMU_PID"] is not None:
        os.kill(STATE["QEMU_PID"], signal.SIGTERM)


def on_sighup_restart_vm():
    def signal_handler(sig, frame):
        interrupt_print("SIGHUP received. restarting VM.")
        kill_vm()

    signal.signal(signal.SIGHUP, signal_handler)


def on_sigterm_terminate():
    def signal_handler(sig, frame):
        interrupt_print("SIGTERM received. Stopping virtual node.")
        STATE["STOPPING"] = True
        kill_vm()

    signal.signal(signal.SIGTERM, signal_handler)


def on_exit():
    vm_pid = STATE["QEMU_PID"]
    if vm_pid is not None:
        kill_vm()
        os.waitpid(vm_pid, 0)


def run():
    atexit.register(on_exit)
    on_sighup_restart_vm()
    on_sigterm_terminate()
    WalTVirtualNode.run()
