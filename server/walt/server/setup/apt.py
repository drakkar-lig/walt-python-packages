import datetime
import os
import subprocess
import sys
from pathlib import Path

import apt
import apt.progress.base

"""
See
https://raphaelhertzog.com/2010/09/21/debian-conffile-configuration-file-managed-by-dpkg
"""
DPKG_CONF_PATH = Path("/etc/dpkg/dpkg.cfg.d/local")
DPKG_CONF_CONTENT = """\
force-confdef
force-confold
"""


def package_is_installed(pname):
    cache = apt.cache.Cache()
    cache.open()
    return pname in cache


def get_debconf_selection(pname, selection_name):
    p = subprocess.run(f"debconf-show {pname}".split(), capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if f"{selection_name}:" in line:
            if line.strip()[0] == "*":
                return " ".join(line.split()[2:])
            else:
                return None


def set_debconf_selection(pname, selection_name, selection_type, selection_value):
    debconf_selection = f"{pname} {selection_name} {selection_type} {selection_value}\n"
    subprocess.run(["debconf-set-selections"], input=debconf_selection, text=True)


def ensure_debconf_selection(pname, selection_name, selection_type, selection_value):
    if get_debconf_selection(pname, selection_name) != selection_value:
        set_debconf_selection(pname, selection_name, selection_type, selection_value)


def fix_dpkg_options():
    print("Tuning package manager for non-interactive use... ", end="")
    sys.stdout.flush()
    conf = DPKG_CONF_PATH
    if not conf.exists() or conf.read_text() != DPKG_CONF_CONTENT:
        conf.write_text(DPKG_CONF_CONTENT)
    ensure_debconf_selection("debconf", "debconf/priority", "select", "critical")
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    print("done")


class AcquireProgress(apt.progress.base.AcquireProgress):
    def __init__(self, global_progress):
        self._global_progress = global_progress

    def fetch(self, item):
        percent = self.fetched_bytes * 100 // self.total_bytes
        self._global_progress.update_acquire(percent)

    def stop(self):
        self._global_progress.update_acquire(None)


class InstallProgress(apt.progress.base.InstallProgress):
    # voir /usr/lib/python3/dist-packages/apt/progress/base.py class InstallProgress
    def __init__(self, global_progress):
        apt.progress.base.InstallProgress.__init__(self)
        self._global_progress = global_progress
        self.saved_stdout = os.dup(1)
        self.log_file = self._global_progress.log_file

    def fork(self):
        pid = os.fork()
        if pid == 0:
            os.dup2(self.log_file.fileno(), 1)  # direct stdout to log file
            os.dup2(self.log_file.fileno(), 2)  # direct stderr to log file
        return pid

    def status_change(self, pkg, percent, status):
        self._global_progress.update_install(int(percent))

    def finishUpdate(self):  # alias, avoid 1 exception report level in case of issue
        self.finish_update()

    def finish_update(self):
        self._global_progress.update_install(100)
        self._global_progress.finish_install()

    def error(self, pkg, errormsg):
        self._global_progress.notify_error(errormsg)


class GlobalProgress:
    def __init__(self, label):
        self._label = label
        self._percent_acquire = None
        self._percent_install = 0
        self._errormsg = None
        timestamp_str = datetime.datetime.now().strftime("%m%d%y%H%M%S")
        self.log_file_path = Path(f"/var/log/walt-server-setup.{timestamp_str}.log")
        self.log_file = self.log_file_path.open("wb")
        os.set_inheritable(self.log_file.fileno(), True)
        self.acquire = AcquireProgress(self)
        self.install = InstallProgress(self)

    def update_acquire(self, percent):
        self._percent_acquire = percent
        self.print_status()

    def update_install(self, percent):
        self._percent_install = percent
        self.print_status()

    def finish_install(self):
        print(end="\r\n")
        if self._errormsg is not None:
            print("An error occured:", end="\r\n")
            print(self._errormsg, end="\r\n")
            self.log_file.close()
            print(f"check out log file for details: {self.log_file_path}", end="\r\n")
            raise Exception("Stopped because of apt process issue.")

    def print_status(self):
        status_line = f"{self._label}: {self._percent_install}%"
        if self._percent_acquire is not None:
            status_line += f" -- downloading {self._percent_acquire}%"
        else:
            status_line += " " * len(" -- downloading 100%")
        print(status_line, end="\r")

    def notify_error(self, errormsg):
        self._errormsg = errormsg


def get_apt_cache():
    Path("/var/cache/apt/archives/partial").mkdir(parents=True, exist_ok=True)
    cache = apt.cache.Cache()
    cache.open()
    return cache


def remove_packages(packages, purge=False):
    cache = get_apt_cache()
    modified = False
    # remove packages
    for pname in packages:
        if pname in cache:
            package = cache.get(pname)
            if package.is_installed:
                package.mark_delete(purge=purge)
                modified = True
    if modified:
        p = GlobalProgress("Removing obsolete OS packages")
        cache.commit(fetch_progress=p.acquire, install_progress=p.install)


def upgrade_and_install_packages(packages, upgrade_packets=False):
    # upgrade and install new packages
    cache = get_apt_cache()
    print("Reloading package cache... ", end="")
    sys.stdout.flush()
    cache.update()
    cache.open()
    print("done")
    modified = False
    for pname in packages:
        package = cache.get(pname)
        if not package.is_installed:
            package.mark_install()
            modified = True
    if upgrade_packets:
        cache.upgrade(True)
        modified = True
    if modified:
        msg = (
            "Installing or upgrading OS packages"
            if upgrade_packets
            else "Installing OS packages"
        )
        p = GlobalProgress(msg)
        cache.commit(fetch_progress=p.acquire, install_progress=p.install)


def autoremove_packages():
    cache = get_apt_cache()
    # autoremove
    modified = False
    for p in cache:
        if p.is_auto_removable:
            p.mark_delete()
            modified = True
    if modified:
        p = GlobalProgress("Removing OS packages no longer needed")
        cache.commit(fetch_progress=p.acquire, install_progress=p.install)
