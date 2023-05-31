#!/usr/bin/env python
import os
import shlex
from pathlib import Path

from walt.server.tools import ensure_text_file_content, get_server_ip

# These env variables should be set by systemd service unit file
STATE_DIRECTORY = Path(os.getenv("STATE_DIRECTORY", "/var/lib/walt/services/snmpd"))
SNMPD_BINARY_NAME = Path(os.getenv("SNMPD_BINARY_NAME", "snmpd"))
SNMPD_USER = Path(os.getenv("SNMPD_USER", "Debian-snmp"))
SNMPD_GROUP = Path(os.getenv("SNMPD_GROUP", "Debian-snmp"))
SNMPD_AGENTX_SOCKET = Path(
    os.getenv("SNMPD_AGENTX_SOCKET", "/run/walt/snmpd/agentx-master.socket")
)
PID_FILE = Path(os.getenv("PIDFILE", "/run/walt/snmpd/snmpd.pid"))

SNMPD_CONF_FILE_CONTENT = f"""\
agentaddress udp:{get_server_ip()}:161
rocommunity private
rouser authOnlyUser
master agentx
agentXSocket {SNMPD_AGENTX_SOCKET}
"""


def get_conf_file():
    conf_file = STATE_DIRECTORY / "snmpd.conf"
    ensure_text_file_content(conf_file, SNMPD_CONF_FILE_CONTENT)
    return conf_file


def run():
    conf_file = get_conf_file()
    cmd = (
        f"{SNMPD_BINARY_NAME} -f -LOw -I -smux"
        f"    -u {SNMPD_USER} -g {SNMPD_GROUP}"
        f"    -p {PID_FILE} -C -c {conf_file}"
    )
    print(cmd)
    os.execvp(SNMPD_BINARY_NAME, shlex.split(cmd))


if __name__ == "__main__":
    run()
