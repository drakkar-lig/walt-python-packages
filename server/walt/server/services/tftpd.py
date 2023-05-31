#!/usr/bin/env python
import os
import shlex
from pathlib import Path

from walt.server.tools import ensure_text_file_content, get_server_ip

# These env variables should be set by systemd service unit file
STATE_DIRECTORY = Path(os.getenv("STATE_DIRECTORY", "/var/lib/walt/services/tftpd"))
TFTPD_BINARY_NAME = Path(os.getenv("TFTPD_BINARY_NAME", "in.tftpd"))
TFTPD_USER = Path(os.getenv("TFTPD_USER", "tftp"))
TFTP_ROOT = Path(os.getenv("TFTP_ROOT", "/var/lib/walt"))
PID_FILE = Path(os.getenv("PIDFILE", "/run/walt/tftpd/tftpd.pid"))

MAP_FILE_CONTENT = """\
# files used for standard PXE booting should not be
# redirected because images of new nodes are not mounted yet
e .*undionly.*
# these two lines ensures compatibility of legacy
# bootloader configurations.
r boot/rpi-.*\\.uboot start.uboot
r boot/pc-x86-64.ipxe start.ipxe
# generic replacement pattern
r .* nodes/\\i/tftp/\\0
"""


def get_map_file():
    map_file = STATE_DIRECTORY / "map"
    ensure_text_file_content(map_file, MAP_FILE_CONTENT)
    return map_file


def run():
    server_ip = get_server_ip()
    map_file = get_map_file()
    cmd = (
        f"{TFTPD_BINARY_NAME} --listen --user {TFTPD_USER}"
        f"    --address {server_ip}:69 -v -v --secure"
        f"    --map-file {map_file} --pidfile {PID_FILE}"
        f"    {TFTP_ROOT}"
    )
    print(cmd)
    os.execvp(TFTPD_BINARY_NAME, shlex.split(cmd))


if __name__ == "__main__":
    run()
