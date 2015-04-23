import subprocess
from plumbum.cmd import cat

def eval_cmd(cmd):
    return cmd()

def get_mac_address(interface):
    return eval_cmd(cat["/sys/class/net/" + interface + "/address"]).strip()

def do(cmd):
    return subprocess.call(cmd, shell=True)

def succeeds(cmd):
    return do(cmd) == 0



