#!/usr/bin/env python
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

from walt.common.apilink import ServerAPILink
from walt.common.fakeipxe import ipxe_start

PRODUCT_NAME_FILE = "/sys/devices/virtual/dmi/id/product_name"
MANUFACTURER_FILE = "/sys/devices/virtual/dmi/id/sys_vendor"


def error(msg):
    print(msg, file=sys.stderr)


def read_system_file(file_path):
    path = Path(file_path)
    if not path.exists():
        error('Error: "' + file_path + '" does not exist!')
        sys.exit(1)
    return path.read_text().strip()


def get_cmdline_value(name, err_exit=True):
    current_cmdline = read_system_file("/proc/cmdline")
    for s in current_cmdline.split():
        if s.startswith(name):
            return s.split("=")[1]
    if err_exit:
        error("Error: no " + name + " definition in /proc/cmdline.")
        sys.exit(1)
    return None


def get_mac():
    mac = get_cmdline_value("walt.node.mac", err_exit=False)
    if mac is not None:
        return mac
    bootif = get_cmdline_value("BOOTIF", err_exit=False)
    if bootif is not None:
        return ":".join(bootif.split("-")[1:])
    error("Error: no walt.node.mac nor BOOTIF definition in /proc/cmdline.")
    sys.exit(1)


# in the context of a reboot, network is already setup,
# and we just retrieve network information (ip, gateway, etc.)
# from the server (this is more robust than parsing local
# interface and routing data).
def add_network_info(env):
    try:
        with ServerAPILink(env["server_ip"], "VSAPI") as server:
            info = server.get_device_info(env["mac"])
            print(info)
            if info is None:
                raise Exception  # forgotten node?
            # check if kexec has been disabled for this node
            if not info["conf"].get("kexec.allow", True):
                error("Kexec is not allowed for this node (cf. walt node config)")
                sys.exit(3)
            env.update(ip=info["ip"],
                       netmask=info["netmask"],
                       gateway=info["gateway"],
                       hostname=info["name"])
    except Exception:
        error("Issue while trying to get node info from server.")
        sys.exit(2)


def get_env_start():
    # define initial env variables for ipxe_boot()
    env = dict(
        product=read_system_file(PRODUCT_NAME_FILE),
        manufacturer=read_system_file(MANUFACTURER_FILE),
        hostname=socket.gethostname().split(".")[0],
        server_ip=get_cmdline_value("walt.server.ip"),
        model=get_cmdline_value("walt.node.model"),
        mac=get_mac(),
    )
    add_network_info(env)
    return env


def kexec_reboot(env):
    # kexec first step (kexec -l)
    cmd_args = "kexec -l %(boot-kernel)s"
    if "boot-initrd" in env:
        cmd_args += " --initrd %(boot-initrd)s"
    if "boot-kernel-cmdline" in env:
        cmd_args += " --command-line '%(boot-kernel-cmdline)s'"
    cmd = cmd_args % env
    print(" ".join(cmd.split()))  # print with multiple spaces shrinked
    subprocess.call(cmd, shell=True)
    # Note: old walt servers did not define this env var walt_boot_mode,
    # but they only had the "network-volatile" boot mode.
    # And "network-volatile" was previously called just "network".
    boot_mode = os.environ.get("walt_boot_mode", "network-volatile")
    print(f"boot-mode: {boot_mode}")
    if boot_mode in ("network", "network-volatile"):
        # in this case, we are on a temporary RAM overlay,
        # so no need to wait for a clean shutdown, we can call
        # "kexec -e" right away.
        subprocess.call("kexec -e", shell=True)
    else:
        # hybrid or unknown mode a new server would provide:
        # we do a clean shutdown, and if the OS is properly
        # configured, a "kexec -e" command will be run by a
        # last service after OS shutdown.
        subprocess.call(["reboot"])


def run():
    if which("kexec") is None:
        error("Sorry, no kexec binary was found.")
        sys.exit(1)
    try:
        env = get_env_start()
        with tempfile.TemporaryDirectory() as tmpdir:
            env["TMPDIR"] = tmpdir
            ipxe_start(env)
            if env["should-boot-kernel"]:
                kexec_reboot(env)
    except NotImplementedError as e:
        error((str(e)))
