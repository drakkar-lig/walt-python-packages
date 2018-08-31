import subprocess, os, sys, json, re, fcntl, signal
from plumbum.cmd import cat
from collections import OrderedDict
from datetime import datetime, timedelta
from fcntl import fcntl, F_GETFD, F_SETFD, FD_CLOEXEC

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
        self.default_label = label
        self.label = label
        self.last_time = None
        self.next_time = None
        self.msg_len = None
    def start(self):
        self.last_time = None
        self.next_time = datetime.now() + PROGRESS_INDICATOR_PERIOD
    def write_stdout(self, s):
        sys.stdout.write(s)
        sys.stdout.flush()
    def update(self):
        if datetime.now() > self.next_time:
            if self.last_time == None:
                msg = self.label + "... *"
                self.write_stdout(msg)
                self.msg_len = len(msg)
            else:
                self.write_stdout("*")
                self.msg_len += 1
            self.last_time = datetime.now()
            self.next_time = self.last_time + PROGRESS_INDICATOR_PERIOD
    def done(self):
        if self.last_time != None:
            self.write_stdout("\r" + (' ' * self.msg_len) + "\r")
    def reset(self):
        self.done()
        self.start()
    def set_label(self, label):
        self.label = label
        if self.last_time != None:
            self.reset()
    def set_default_label(self):
        self.set_label(self.default_label)

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
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

def remove_non_utf8(s):
    return s.decode('utf-8','ignore').encode("utf-8")

def on_sigterm_throw_exception():
    def signal_handler(signal, frame):
        print('SIGTERM received.')
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, signal_handler)

MAX_PRINTED_NODES = 10
CONJUGATE_REGEXP = r'\b(\w*)\((\w*)\)'

def format_sentence_about_nodes(sentence, nodes):
    """
    example 1:
        input: sentence = '% seems(seem) dead.', nodes = ['rpi0']
        output: 'Node rpi0 seems dead.'
    example 2:
        input: sentence = '% seems(seem) dead.', nodes = ['rpi0', 'rpi1', 'rpi2']
        output: 'Nodes rpi0, rpi1 and rpi2 seem dead.'
    (and if there are many nodes, an ellipsis is used.)
    """
    # conjugate if plural or singular
    if len(nodes) == 1:
        sentence = re.sub(CONJUGATE_REGEXP, r'\1', sentence)
    else:
        sentence = re.sub(CONJUGATE_REGEXP, r'\2', sentence)
    # designation of nodes
    sorted_nodes = sorted(nodes)
    if len(nodes) > MAX_PRINTED_NODES:
        s_nodes = 'Nodes %s, %s, ..., %s' % (sorted_nodes[0], sorted_nodes[1], sorted_nodes[-1])
    elif len(nodes) == 0:
        s_nodes = 'No nodes'
    elif len(nodes) > 1:
        s_nodes = 'Nodes %s and %s' % (', '.join(sorted_nodes[:-1]), sorted_nodes[-1])
    else:
        s_nodes = 'Node %s' % tuple(nodes)
    # almost done
    return sentence % s_nodes

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

