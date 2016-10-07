import subprocess, os, sys, json, re
from plumbum.cmd import cat
from collections import OrderedDict
from datetime import datetime, timedelta

DEVNULL = open(os.devnull, 'w')

def eval_cmd(cmd):
    return cmd()

def get_mac_address(interface):
    return eval_cmd(cat["/sys/class/net/" + interface + "/address"]).strip()

def do(cmd):
    return subprocess.call(cmd, stdout=DEVNULL, shell=True)

def succeeds(cmd):
    return do(cmd) == 0

def failsafe_makedirs(path):
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

def failsafe_mkfifo(path):
    # check if it does not exist already
    if os.path.exists(path):
        return
    # ensure parent dir exists
    failsafe_makedirs(os.path.dirname(path))
    # create the fifo
    os.mkfifo(path)

# Note: json comments are not allowed in the standard
# and thus not handled in the json python module.
# We handle them manually.
def read_json(file_path):
    content = None
    try:
        with open(file_path) as f:
            # filter out comments
            filtered = re.sub('#.*', '', f.read())
            # read valid json
            content = json.loads(filtered, object_pairs_hook=OrderedDict)
    except:
        pass
    return content

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

PROGRESS_INDICATOR_PERIOD = timedelta(seconds=1.0)

class BusyIndicator(object):
    def __init__(self, label):
        self.label = label
        self.last_time = None
        self.next_time = None
    def start(self):
        self.last_time = None
        self.next_time = datetime.now() + PROGRESS_INDICATOR_PERIOD
    def write_stdout(self, s):
        sys.stdout.write(s)
        sys.stdout.flush()
    def update(self):
        if datetime.now() > self.next_time:
            if self.last_time == None:
                self.write_stdout(self.label + "... *")
            else:
                self.write_stdout("*")
            self.last_time = datetime.now()
            self.next_time = self.last_time + PROGRESS_INDICATOR_PERIOD
    def done(self):
        if self.last_time != None:
            self.write_stdout("\n")
    def reset(self):
        self.done()
        self.start()
