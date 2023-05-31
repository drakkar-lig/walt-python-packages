import sys

from walt.server.config import check_conf, get_conf


def __getattr__(name):
    # Lazy-loading of the configuration: at setup time, this file
    # does not exist yet
    if name == "conf":
        check_conf()
        conf = get_conf()
        setattr(sys.modules[__name__], name, conf)
        return conf
    raise AttributeError(name)
