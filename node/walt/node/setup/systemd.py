#!/usr/bin/env python
from walt.common.tools import failsafe_symlink
from pkg_resources import resource_filename
import shutil

SYSTEMD_SERVICES = [ "walt-logs.service" ]
SYSTEMD_SERVICES_DIR = "/etc/systemd/system"
SYSTEMD_INSTALL_DIR = "/etc/systemd/system/multi-user.target.wants"

def run():
    for service in SYSTEMD_SERVICES:
        service_path = resource_filename(__name__, service)
        shutil.copy(service_path, SYSTEMD_SERVICES_DIR)
        # the following is the same as running 'systemctl enable <service>'
        # on a system that is really running
        failsafe_symlink(SYSTEMD_SERVICES_DIR + '/' + service,
                         SYSTEMD_INSTALL_DIR + '/' + service)
