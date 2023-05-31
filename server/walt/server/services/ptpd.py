#!/usr/bin/env python
import os
import shlex
from pathlib import Path

from walt.server.tools import ensure_text_file_content

# These env variables should be set by systemd service unit file
STATE_DIRECTORY = Path(os.getenv("STATE_DIRECTORY", "/var/lib/walt/services/ptpd"))
PTPD_BINARY_NAME = Path(os.getenv("PTPD_BINARY_NAME", "ptpd"))
PTPD_STATUS_FILE = Path(os.getenv("PTPD_STATUS_FILE", "/run/walt/ptpd/ptpd.status"))

PTPD_CONF_CONTENT = f"""\
ptpengine:interface=walt-net
ptpengine:preset=masteronly
global:cpuaffinity_cpucore=0
global:ignore_lock=Y
global:use_syslog=Y
global:log_status=Y
global:log_level=LOG_NOTICE
global:status_file={PTPD_STATUS_FILE}
global:foreground=Y
ptpengine:domain=42
ptpengine:ip_dscp=46
ptpengine:ip_mode=hybrid
ptpengine:log_delayreq_interval=3
ptpengine:log_sync_interval=3
ptpengine:log_announce_interval=3
"""


def get_conf_file():
    conf_file = STATE_DIRECTORY / "ptpd.conf"
    ensure_text_file_content(conf_file, PTPD_CONF_CONTENT)
    return conf_file


def run():
    conf_file = get_conf_file()
    cmd = f"{PTPD_BINARY_NAME} -c {conf_file}"
    print(cmd)
    os.execvp(PTPD_BINARY_NAME, shlex.split(cmd))


if __name__ == "__main__":
    run()
