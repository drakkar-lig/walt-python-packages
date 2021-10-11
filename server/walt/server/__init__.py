import sys

from walt.server.config import get_conf

def __getattr__(name):
    # Lazy-loading of the configuration: at setup time, this file
    # does not exist yet
    if name == 'conf':
        conf = get_conf()
        setattr(sys.modules[__name__], name, conf)
        return conf
    raise AttributeError(name)
