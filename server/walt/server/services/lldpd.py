#!/usr/bin/env python
import os
import shlex
from pathlib import Path

from walt.server import conf
from walt.server.tools import get_server_ip

# These env variables should be set by systemd service unit file
RUNTIME_DIRECTORY = Path(os.getenv("RUNTIME_DIRECTORY", "/run/walt/lldpd"))
LLDPD_BINARY_NAME = Path(os.getenv("LLDPD_BINARY_NAME", "lldpd"))
SNMPD_AGENTX_SOCKET = Path(
    os.getenv("SNMPD_AGENTX_SOCKET", "/run/walt/snmpd/agentx-master.socket")
)
PID_FILE = Path(os.getenv("PIDFILE", "/run/walt/lldpd/lldpd.pid"))


def get_walt_net_physical_interface():
    return conf["network"]["walt-net"].get("raw-device", None)


def run():
    socket = RUNTIME_DIRECTORY / "lldpd.socket"
    phys_intf = get_walt_net_physical_interface()
    if phys_intf is None:
        intf_options = ""  # fallback to listening on all physical interfaces
    else:
        intf_options = f"-I {phys_intf} -C {phys_intf}"
    management_ip = get_server_ip()
    cmd = (
        f"{LLDPD_BINARY_NAME} -c -s -e -X {SNMPD_AGENTX_SOCKET}"
        f"    {intf_options} -m {management_ip}"
        f"    -u {socket} -D snmp -p {PID_FILE}"
    )
    print(cmd)
    os.execvp(LLDPD_BINARY_NAME, shlex.split(cmd))


if __name__ == "__main__":
    run()
