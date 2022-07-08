from __future__ import annotations

import json
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
from collections import OrderedDict
from fcntl import fcntl, F_GETFD, F_SETFD, F_GETFL, F_SETFL, FD_CLOEXEC
from pathlib import Path

DEVNULL = open(os.devnull, 'w')

def get_mac_address(interface):
    return Path("/sys/class/net/" + interface + "/address").read_text().strip()

def do(cmd: str | [str], shell=False):
    """Exec a system command, return the command's returncode."""
    if not shell and isinstance(cmd, str):
        # Split command-line in an array
        cmd = shlex.split(cmd)
    return subprocess.call(cmd, stdout=DEVNULL, shell=shell)

def succeeds(cmd):
    return do(cmd) == 0

def failsafe_makedirs(path):
    # remove if not a dir
    if os.path.lexists(path) and not os.path.isdir(path):
        os.remove(path)
    # create only if missing
    if not os.path.exists(path):
        os.makedirs(path)

def failsafe_symlink(src_target, dst_path, force_relative = False):
    # if force_relative, turn src_target into a relative path
    if force_relative:
        targetwords = src_target.rstrip('/').split('/')
        pathwords = os.path.dirname(dst_path).split('/')
        num_common = len([x for x, y in zip(targetwords, pathwords) if x == y])
        relativewords = [ '..' ] * (len(pathwords) - num_common) + targetwords[num_common:]
        src_target = '/'.join(relativewords)
    # remove existing symlink if any
    if os.path.lexists(dst_path):
        if os.readlink(dst_path) == src_target:
            # nothing to do
            return
        else:
            # symlink target (src_target) has changed
            os.remove(dst_path)
    # ensure parent dir of dst_path exists
    failsafe_makedirs(os.path.dirname(dst_path))
    # create the symlink
    os.symlink(src_target, dst_path)

# use the following like this:
#
# with AutoCleaner(<obj>) as <var>:
#     ... work_with <var> ...
#
# <obj> must provide a method cleanup()
# that will be called automatically when leaving
# the with construct.

class AutoCleaner(object):
    def __init__(self, obj):
        self.obj = obj
    def __enter__(self):
        return self.obj
    def __exit__(self, t, value, traceback):
        self.obj.cleanup()
        self.obj = None

# look for a kernel parameter in /proc/cmdline
# if in the form <arg>=<val> return <val>
# if in the form <arg> return True
# if not found return None

def get_kernel_bootarg(in_bootarg):
    with open('/proc/cmdline') as f:
        for bootarg in f.read().split():
            name, val = (bootarg.split('=') + [ True ])[:2]
            if name == in_bootarg:
                return val

class RealBusyIndicator:
    def __init__(self, label):
        self.default_label = label
        self.label = label
        self.msg_len = 0
        self.char_idx = 0
    def start(self):
        self.char_idx = 0
    def write_stdout(self, s):
        sys.stdout.write(s)
        sys.stdout.flush()
    def update(self):
        wheel_char = "\\|/-"[self.char_idx]
        self.erase_previous()
        msg = self.label + "... " + wheel_char
        self.write_stdout(msg)
        self.msg_len = len(msg)
        self.char_idx = (self.char_idx+1) % 4
    def erase_previous(self):
        self.write_stdout("\r" + (' ' * self.msg_len) + "\r")
    def done(self):
        self.reset()
    def reset(self):
        self.erase_previous()
    def set_label(self, label):
        self.label = label
    def set_default_label(self):
        self.set_label(self.default_label)

class SilentBusyIndicator:
    def __getattr__(self, attr):
        return lambda *args: None

class BusyIndicator:
    def __new__(cls, *args):
        is_interactive = os.isatty(sys.stdout.fileno()) and \
                            os.isatty(sys.stdin.fileno())
        if is_interactive:
            return RealBusyIndicator(*args)
        else:
            return SilentBusyIndicator()

def fd_copy(fd_src, fd_dst, size):
    try:
        s = os.read(fd_src, size)
        if len(s) == 0:
            return None
        os.write(fd_dst, s)
        return s
    except:
        return None

def set_non_blocking(fd):
    fl = fcntl(fd, F_GETFL)
    fcntl(fd, F_SETFL, fl | os.O_NONBLOCK)

def remove_non_utf8(s):
    return s.decode('utf-8','ignore').encode("utf-8")

def on_sigterm_throw_exception():
    def signal_handler(signal, frame):
        print('SIGTERM received.')
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, signal_handler)

class SimpleContainer(object):
    def __init__(self, **args):
        self.update(**args)
    def update(self, **args):
        self.__dict__.update(**args)
        return self
    def copy(self):
        return SimpleContainer(**self.__dict__)

def serialize_ordered_dict(od):
    res = []
    for k, v in od.items():
        if isinstance(v, OrderedDict):
            v = serialize_ordered_dict(v)
        res.append((k, v))
    return tuple(res)

def deserialize_ordered_dict(t):
    d = OrderedDict()
    for k, v in t:
        if isinstance(v, tuple):
            v = deserialize_ordered_dict(v)
        d[k] = v
    return d

def set_close_on_exec(fd, close_on_exec):
    val = fcntl(fd, F_GETFD)
    if close_on_exec:
        val |= FD_CLOEXEC
    else:
        val &= ~FD_CLOEXEC
    fcntl(fd, F_SETFD, val)

def restart():
    os.execvp(sys.argv[0], sys.argv)

def chown_tree(path, user, group):
    for p_entry in Path(path).iterdir():
        if p_entry.is_dir():
            chown_tree(p_entry, user, group)
        else:
            shutil.chown(str(p_entry), user, group)
    shutil.chown(str(path), user, group)

def verify_root_login_shell():
    if os.getuid() != 0:
        raise Exception('This command must be run as root. Aborting.')
    if os.environ.get('LOGNAME') != 'root':
        print('This command must be run in a root login shell.')
        print('If you first logged in as a different user, use `su --login root`.')
        raise Exception('This command must be run in a root login shell. Aborting.')

def get_persistent_random_mac(mac_file):
    mac_file_path = Path(mac_file)
    if mac_file_path.exists():
        return mac_file_path.read_text().strip()
    else:
        mac = ':'.join(["%02x" % x for x in [ 0x52, 0x54, 0x00,
                            random.randint(0x00, 0x7f),
                            random.randint(0x00, 0xff),
                            random.randint(0x00, 0xff) ]])
        mac_file_path.write_text(mac + '\n')
        return mac
