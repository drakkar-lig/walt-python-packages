from collections import namedtuple

from walt.server import conf
from walt.server.autoglob import autoglob
import pickle, resource

# are you sure you want to understand what follows? This is sorcery...
nt_index = 0
nt_classes = {}
def to_named_tuple(d):
    global nt_index
    code = pickle.dumps(sorted(d.keys()))
    if code not in nt_classes:
        base = namedtuple('NamedTuple_%d' % nt_index, list(d.keys()))
        class NT(base):
            def update(self, **kwargs):
                d = self._asdict()
                d.update(**kwargs)
                return to_named_tuple(d)
        nt_classes[code] = NT
        nt_index += 1
    return nt_classes[code](**d)

def merge_named_tuples(nt1, nt2):
    d = nt1._asdict()
    d.update(nt2._asdict())
    return to_named_tuple(d)

def update_template(path, template_env):
        with open(path, 'r+') as f:
            template_content = f.read()
            file_content = template_content % template_env
            f.seek(0)
            f.write(file_content)
            f.truncate()

def try_encode(s, encoding):
    if encoding is None:
        return False
    try:
        s.encode(encoding)
        return True
    except UnicodeError:
        return False

def format_node_models_list(node_models):
    return autoglob(node_models)

# max number of file descriptors this process is allowed to open
SOFT_RLIMIT_NOFILE = 16384

def set_rlimits():
    soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (SOFT_RLIMIT_NOFILE, hard_limit))

def get_server_ip() -> str:
    """Load the server IP address on walt-net from the configuration file."""
    return conf['network']['walt-net']['ip'].split('/')[0]
