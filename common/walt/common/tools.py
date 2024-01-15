from __future__ import annotations

import os
import sys
from fcntl import F_GETFD, F_GETFL, F_SETFD, F_SETFL, FD_CLOEXEC, fcntl
from functools import lru_cache   # note: python3.7 has no functools.cache decorator
from pathlib import Path


def get_mac_address(interface):
    return Path("/sys/class/net/" + interface + "/address").read_text().strip()


def do(cmd: str | [str], shell=False, stdout=None, stderr=None, text=True):
    """Exec a system command, return the command's returncode."""
    from select import select
    from subprocess import PIPE, Popen

    if not shell and isinstance(cmd, str):
        # Split command-line in an array
        import shlex

        cmd = shlex.split(cmd)
    with Popen(
        cmd, shell=shell, stdout=PIPE, stderr=PIPE, text=text, bufsize=0
    ) as proc:
        pipes_proc_to_caller = {proc.stdout: stdout, proc.stderr: stderr}
        pipes = list(pipes_proc_to_caller.keys())
        # by default, a read() on a pipe will block until the pipe is closed.
        # set it to non-blocking to prevent this behavior.
        for f in pipes:
            fd = f.fileno()
            fl = fcntl(fd, F_GETFL)
            fcntl(fd, F_SETFL, fl | os.O_NONBLOCK)
        while len(pipes) > 0:
            r, w, e = select(pipes, [], [])
            for f in r:
                chunk = f.read()
                if len(chunk) == 0:
                    pipes.remove(f)
                else:
                    caller_pipe = pipes_proc_to_caller[f]
                    if caller_pipe is not None:
                        caller_pipe.write(chunk)
    return proc.returncode


def succeeds(cmd):
    return do(cmd) == 0


def failsafe_makedirs(path):
    # remove if not a dir
    if os.path.lexists(path) and not os.path.isdir(path):
        os.remove(path)
    # create only if missing
    if not os.path.exists(path):
        os.makedirs(path)


def failsafe_symlink(src_target, dst_path, force_relative=False):
    # if force_relative, turn src_target into a relative path
    if force_relative:
        targetwords = src_target.rstrip("/").split("/")
        pathwords = os.path.dirname(dst_path).split("/")
        num_common = len([x for x, y in zip(targetwords, pathwords) if x == y])
        relativewords = [".."] * (len(pathwords) - num_common) + targetwords[
            num_common:
        ]
        src_target = "/".join(relativewords)
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
    with open("/proc/cmdline") as f:
        for bootarg in f.read().split():
            name, val = (bootarg.split("=") + [True])[:2]
            if name == in_bootarg:
                return val


class RealBusyIndicator:
    @lru_cache(maxsize=None)
    def __new__(cls, label):
        return object.__new__(cls)

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
        self.char_idx = (self.char_idx + 1) % 4

    def erase_previous(self):
        self.write_stdout("\r" + (" " * self.msg_len) + "\r")

    def done(self):
        self.reset()

    def reset(self):
        self.erase_previous()

    def set_label(self, label):
        self.label = label

    def set_default_label(self):
        self.set_label(self.default_label)

    def get_label(self):
        return self.label


class SilentBusyIndicator:
    @lru_cache(maxsize=None)
    def __new__(cls):
        return object.__new__(cls)

    def __getattr__(self, attr):
        return lambda *args: None


class BusyIndicator:
    def __new__(cls, *args):
        is_interactive = os.isatty(sys.stdout.fileno()) and os.isatty(
            sys.stdin.fileno()
        )
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
    except Exception:
        return None


def set_non_blocking(fd):
    fl = fcntl(fd, F_GETFL)
    fcntl(fd, F_SETFL, fl | os.O_NONBLOCK)


def remove_non_utf8(s):
    return s.decode("utf-8", "ignore").encode("utf-8")


# Caution: if we are in an interrupt handler, and the process
# is catching its stdout stream for soem reason, calling print()
# could cause re-entrant calls in some cases.
def interrupt_print(s):
    os.write(1, f"{s}\n".encode())


def on_sigterm_throw_exception():
    import signal

    def signal_handler(signal, frame):
        interrupt_print("SIGTERM received.")
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
    import shutil

    for p_entry in Path(path).iterdir():
        if p_entry.is_dir():
            chown_tree(p_entry, user, group)
        else:
            shutil.chown(str(p_entry), user, group)
    shutil.chown(str(path), user, group)


def verify_root_login_shell():
    if os.getuid() != 0:
        raise Exception("This command must be run as root. Aborting.")
    if os.environ.get("LOGNAME") != "root":
        print("This command must be run in a root login shell.")
        print("If you first logged in as a different user, use `su --login root`.")
        raise Exception("This command must be run in a root login shell. Aborting.")


def get_persistent_random_mac(mac_file):
    mac_file_path = Path(mac_file)
    if mac_file_path.exists():
        return mac_file_path.read_text().strip()
    else:
        import random

        mac = ":".join(
            [
                "%02x" % x
                for x in [
                    0x52,
                    0x54,
                    0x00,
                    random.randint(0x00, 0x7F),
                    random.randint(0x00, 0xFF),
                    random.randint(0x00, 0xFF),
                ]
            ]
        )
        mac_file_path.write_text(mac + "\n")
        return mac


def parse_image_fullname(image_fullname):
    image_user, image_name = image_fullname.split("/")
    if image_name.endswith(":latest"):
        image_name = image_name[:-7]
    elif ":" not in image_fullname:
        image_fullname += ":latest"
    return image_fullname, image_user, image_name


def format_image_fullname(user, image_name):
    if ":" in image_name:
        repo, tag = image_name.split(":", maxsplit=1)
    else:
        repo, tag = image_name, "latest"
    return user + "/" + repo + ":" + tag
