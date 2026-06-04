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
from os import getenv, getpid, truncate
from pathlib import Path

from importlib.resources import files
from plumbum import cli
from walt.common.apilink import ServerAPILink
from walt.common.evloop import EventLoop
from walt.common.fakeipxe import ipxe_start
from walt.common.logs import LoggedApplication
from walt.common.settings import parse_vnode_disks_value, parse_vnode_networks_value
from walt.common.tools import get_persistent_random_mac, interrupt_print

OS_ENCODING = sys.stdout.encoding
VNODE_PID_PATH = "/var/lib/walt/nodes/%(mac)s/pid"
VNODE_DISKS_PATH = "/var/lib/walt/nodes/%(mac)s/disks"
VNODE_NETWORKS_PATH = "/var/lib/walt/nodes/%(mac)s/networks"
VNODE_FS_PATH = "/var/lib/walt/nodes/%(mac)s/fs"
VNODE_IFUP_SCRIPT_TEMPLATE = "walt-vnode-ifup"
VNODE_IFDOWN_SCRIPT_TEMPLATE = "walt-vnode-ifdown"

# the following values have been selected from output of
# qemu-system-<host-cpu> -machine help
QEMU_MACHINE_DEF = "-machine pc -cpu host"
QEMU_PRODUCT = "Standard PC (i440FX + PIIX, 1996)"
QEMU_APPEND = ""
QEMU_NET_DRIVER = "virtio-net-pci"

MANUFACTURER = "QEMU"
QEMU_PROG = "qemu-system-x86_64"
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
    "             -nographic -serial mon:stdio -no-reboot"
    "             -kernel %(boot-kernel)s"
)
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


def apply_disk_template(disk_path, disk_template):
    if disk_template == "none":
        return  # nothing to do
    elif disk_template == "swap":
        part_type = "82"    # "Linux swap"
        mkfs = "mkswap"
    elif disk_template == "fat32":
        part_type = "0c"    # "W95 FAT32 (LBA)"
        mkfs = "mkfs.vfat -S 512"
    elif disk_template == "ext4":
        part_type = "83"    # "Linux"
        mkfs = "mkfs.ext4"
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


def get_qemu_disks_args(app):
    disks_path = VNODE_DISKS_PATH % dict(mac=app._mac)
    parsing = parse_vnode_disks_value(app._disks)
    if parsing[0] is False:
        raise ValueError(f"Invalid value for disks: {parsing[1]}")
    for warn in parsing[2]:
        print(f"{warn}\n")
    disks_info = parsing[1]
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
            # If not expected size or template, remove it.
            # We remove it too if the template is "swap", because
            # this kind of virtual disk does not need to be persistent.
            # Removing and re-creating this virtual swap disk at each
            # vnode reboot allows to minimize the server disk usage
            # since the virtual swap disk is mostly made of a large
            # hole at first.
            if disk_path.stat().st_size != disk_cap_bytes or \
                    old_disk_template != disk_template or \
                    old_disk_template == 'swap':
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


def get_qemu_networks_args(app):
    hostmac, hostname = app._mac, app._hostname
    networks_path = VNODE_NETWORKS_PATH % dict(mac=app._mac)
    parsing = parse_vnode_networks_value(app._networks)
    if parsing[0] is False:
        raise ValueError(f"Invalid value for networks: {parsing[1]}")
    networks_info = parsing[1]
    import walt.virtual.node
    this_dir = files(walt.virtual.node)
    Path(networks_path).mkdir(parents=True, exist_ok=True)
    qemu_networks_opts = ""
    for network_name, network_restrictions in networks_info.items():
        ifup_script = Path(networks_path) / f"{network_name}-ifup.sh"
        ifdown_script = Path(networks_path) / f"{network_name}-ifdown.sh"
        intf_alias = f"tap to {network_name} of {hostname}"
        if "lat_us" not in network_restrictions:
            network_restrictions["lat_us"] = ""
        if "bw_Mbps" not in network_restrictions:
            network_restrictions["bw_Mbps"] = ""
        for path, template_name in (
            (ifup_script, VNODE_IFUP_SCRIPT_TEMPLATE),
            (ifdown_script, VNODE_IFDOWN_SCRIPT_TEMPLATE),
        ):
            template = (this_dir / template_name).read_text()
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


def ram_text_to_megabytes(ram_value):
    if re.match(r"^\d+[MG]$", ram_value) is None:
        raise ValueError(
            "Invalid RAM amount specified (should be for instance 512M or 1G)."
        )
    # convert to megabytes
    ram_megabytes = int(ram_value[:-1])
    if ram_value[-1] == "G":
        ram_megabytes *= 1024
    return ram_megabytes


def check_boot_delay(delay_value):
    if delay_value != "random":
        try:
            delay_value = int(delay_value)
        except ValueError:
            raise ValueError(
                'Invalid value for --boot-delay (use int value or "random")')
        if delay_value < 0:
            raise ValueError(
                "Invalid value for --boot-delay (use a positive value)")
    return delay_value


class VMParameters(dict):
    # subclass of dict, but allow dot-based accesses too
    def __getattr__(self, attr):
        return self.__getitem__(attr)

    def __setattr__(self, attr, value):
        return self.__setitem__(attr, value)


def get_env_start(app):
    # define initial env variables for ipxe_start()
    env = VMParameters()
    env.TMPDIR = app.TMPDIR
    env.fs_path = VNODE_FS_PATH % dict(mac = app._mac)
    env.manufacturer = MANUFACTURER
    env.product = QEMU_PRODUCT
    env.hostname = app._hostname
    env.hostid = env.hostname
    env.mac = app._mac
    env.ip = app._ip
    # the following data is not necessary for ipxe_start() function
    # but will be used when launching the boot-function boot_kvm()
    env.cpu_cores = app._cpu_cores
    env.ram_megabytes = ram_text_to_megabytes(app._ram)
    env.qemu_disks_args = get_qemu_disks_args(app)
    env.qemu_networks_args = get_qemu_networks_args(app)
    env.boot_delay = check_boot_delay(app._boot_delay)
    env.server_ip = app._server_ip
    env.netmask = app._netmask
    env.gateway = app._gateway
    return env


def get_vm_args(env):
    """Compute whole set of qemu args"""
    qemu_args = QEMU_ARGS
    qemu_args += (f" -virtfs local,id=dev,path={env.fs_path},"
                  "security_model=none,mount_tag=walt_image,readonly=on")
    if "boot-initrd" in env:
        qemu_args += " -initrd %(boot-initrd)s"
    env["boot-kernel-cmdline"] = (
            env.get("boot-kernel-cmdline", "") + " " + QEMU_APPEND)
    if len(env["boot-kernel-cmdline"].strip()) > 0:
        qemu_args += " -append '%(boot-kernel-cmdline)s'"
    cmd = qemu_args % env
    args = shlex.split(cmd)
    print(shlex.join(args))  # print with multiple spaces shrinked
    return args


class QemuStdoutWriter:
    def __init__(self, ev_loop):
        self._ev_loop = ev_loop
        self._buffer = b""
    def write(self, data):
        # we bufferize a little to avoid logging many small
        # vnode console chunks
        if len(self._buffer) > 0:
            self._buffer += data
        else:
            self._buffer = data
            self._ev_loop.plan_event(
                    time.time() + STDOUT_BUFFERING_TIME,
                    target=self)
    def handle_planned_event(self):
        os.write(1, self._buffer.replace(b"\n", b"\r\n"))
        self._buffer = b""


class StdinListener:
    def __init__(self, vm):
        self._vm = vm
        self._stdin_buffer = b''

    def fileno(self):
        return 0  # stdin

    def handle_event(self, ts):
        chunk = os.read(0, 256)
        if len(chunk) == 0:
            print("empty read on stdin, aborting.")
            sys.exit()
        self._stdin_buffer += chunk
        while b'\n' in self._stdin_buffer:
            line, self._stdin_buffer = self._stdin_buffer.split(
                                                b'\n', maxsplit=1)
            line = line.decode(sys.stdin.encoding)
            args = line.split(" ")
            if len(args) == 0:
                continue    # empty line, ignore
            if args[0] == "CONF":
                self._vm.set_conf(args[1], args[2])
            elif args[0] == "INPUT":
                input_bytes = base64.b64decode(args[1])
                self._vm.input(input_bytes)
            elif args[0] == "KILL_VM":
                self._vm.kill()
            elif args[0] == "EXIT":
                self._vm.kill()
                sys.exit()
                break
            else:
                print(f"Invalid command, ignored: {line}")
                continue

    def close(self):
        pass


class VirtualMachine:
    def __init__(self, app):
        self._app = app
        self._ev_loop = EventLoop()
        self._qemu_stdout_writer = QemuStdoutWriter(self._ev_loop)
        self._steps = ["load_env",
                       "wait_fs",
                       "boot_delay",
                       "start_ipxe",
                       "start_qemu" ]
        self._env = None
        self._step = 0
        self._qemu_process = None
    def set_conf(self, name, value):
        # change attribute of self._app, and it will be
        # taken into account at next call to self.load_env()
        setattr(self._app, "_" + name, value)
    def input(self, input_bytes):
        if self._qemu_process is not None:
            try:
                self._qemu_process.stdin.write(input_bytes)
            except Exception:
                print("\nWarning: could not write input data to"
                      " the virtual machine.", file=sys.stderr)
    def kill(self, sig=signal.SIGTERM):
        if self._qemu_process is not None:
            try:
                os.kill(self._qemu_process.pid, sig)
            except Exception:
                pass
    def run(self):
        stdin_listener = StdinListener(self)
        self._ev_loop.register_listener(stdin_listener)
        # plan first step of start procedure asap
        self._ev_loop.plan_event(ts=time.time(),
                                 callback=self.run_next_step)
        self._ev_loop.loop()
    def run_next_step(self):
        step_method = getattr(self, self._steps[self._step])
        self._step += 1
        step_method()
    def load_env(self):
        self._env = get_env_start(self._app)
        self.run_next_step()
    def wait_fs(self):
        fs_path = Path(self._env.fs_path)
        if fs_path.exists() and len(list(fs_path.iterdir())) > 0:
            # ok, image fs is ready
            self.run_next_step()
        else:
            # retry in 1 second
            print("Waiting for OS image mount...")
            self._ev_loop.plan_event(ts=time.time()+1,
                                     callback=self.wait_fs)
    def boot_delay(self, secs=None):
        if secs is None:
            if self._env.boot_delay == "random":
                # default is to wait randomly to mitigate
                # simultaneous load of various virtual nodes
                secs = int(random.random() * 10) + 1
            else:
                secs = self._env.boot_delay
        if secs == 0:
            self.run_next_step()
        else:
            print("waiting for %ds" % secs)
            self._ev_loop.plan_event(ts=time.time()+1,
                                     callback=self.boot_delay,
                                     secs=secs-1)
    def start_ipxe(self):
        print("Starting...")
        ipxe_start(self._env)
        if self._env["should-boot-kernel"]:
            self.run_next_step()
        else:
            self.reset(1)
    def start_qemu(self):
        args = get_vm_args(self._env)
        self._qemu_process = self._ev_loop.do(
                shlex.join(args),
                silent=False,
                pipe_stdout=self._qemu_stdout_writer,
                pipe_stderr=self._qemu_stdout_writer,
                callback=self.reset,
        )
    def reset(self, retcode):
        # return to the start of the procedure
        self._step = 0
        self._qemu_process = None
        self.run_next_step()


class WalTVirtualNode(LoggedApplication):
    _cpu_cores = DEFAULT_QEMU_CORES
    _ram = DEFAULT_QEMU_RAM
    _disks = DEFAULT_QEMU_DISKS
    _networks = DEFAULT_QEMU_NETWORKS
    _boot_delay = DEFAULT_BOOT_DELAY
    vm = None
    TMPDIR = None

    """run a virtual node"""

    def main(self):
        WalTVirtualNode.instance = self
        random.seed()
        self.init_logs()
        self.save_pid()
        self.vm = VirtualMachine(self)
        with tempfile.TemporaryDirectory() as self.TMPDIR:
            self.vm.run()

    def save_pid(self):
        pid_path = VNODE_PID_PATH % dict(mac=self._mac)
        pid_path = Path(pid_path)
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text("%d\n" % getpid())

    @cli.switch("--mac", str, mandatory=True)
    def mac(self, mac_address):
        """specify node's mac address"""
        self._mac = mac_address

    @cli.switch("--ip", str, mandatory=True)
    def ip(self, ip):
        """specify node's ip"""
        self._ip = ip

    @cli.switch("--netmask", str, mandatory=True)
    def netmask(self, netmask):
        """specify node's netmask"""
        self._netmask = netmask

    @cli.switch("--gateway", str, mandatory=True)
    def gateway(self, gateway):
        """specify node's gateway"""
        self._gateway = gateway

    @cli.switch("--server-ip", str, mandatory=True)
    def server_ip(self, server_ip):
        """specify walt server ip"""
        self._server_ip = server_ip

    @cli.switch("--hostname", str, mandatory=True)
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

    @cli.switch("--boot-delay", str)
    def set_boot_delay(self, delay):
        """define a delay before the VM [re]boots (number of seconds or "random")"""
        self._boot_delay = delay


def get_vm():
    return WalTVirtualNode.vm


def kill_vm(sig=signal.SIGTERM):
    vm = get_vm()
    if vm is not None:
        vm.kill(sig)


def on_sighup_restart_vm():
    def signal_handler(sig, frame):
        interrupt_print("SIGHUP received. restarting VM.")
        kill_vm()

    signal.signal(signal.SIGHUP, signal_handler)


def on_sigterm_terminate():
    def signal_handler(sig, frame):
        interrupt_print("SIGTERM received. Stopping virtual node.")
        kill_vm()
        sys.exit()

    signal.signal(signal.SIGTERM, signal_handler)


def on_exit():
    kill_vm(signal.SIGKILL)


def run():
    atexit.register(on_exit)
    on_sighup_restart_vm()
    on_sigterm_terminate()
    WalTVirtualNode.run()
