import subprocess, os
from plumbum.cmd import cat

def eval_cmd(cmd):
    return cmd()

def get_mac_address(interface):
    return eval_cmd(cat["/sys/class/net/" + interface + "/address"]).strip()

def do(cmd):
    return subprocess.call(cmd, shell=True)

def succeeds(cmd):
    return do(cmd) == 0

def failsafe_makedirs(path):
    # create only if missing
    if not os.path.exists(path):
        os.makedirs(path)

def failsafe_symlink(src, dst):
    # remove existing symlink if any
    if os.path.lexists(dst):
        os.remove(dst)
    # ensure parent dir of dst exists
    failsafe_makedirs(os.path.dirname(dst))
    # create the symlink
    os.symlink(src, dst)

def failsafe_mkfifo(path):
    # check if it does not exist already
    if os.path.exists(path):
        return
    # ensure parent dir exists
    failsafe_makedirs(os.path.dirname(path))
    # create the fifo
    os.mkfifo(path)


