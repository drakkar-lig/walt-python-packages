"""Server configuration management."""
import copy

from walt.common.tools import read_json

SERVER_CONF = '/etc/walt/server.conf'
DEFAULT_CONF = {
    "services": {
        "nfsd": {
            "service-name": "nfs-kernel-server.service",
        },
    }
}

def get_conf():
    """Load the server configuration"""
    conf = copy.copy(DEFAULT_CONF)
    conf.update(read_json(SERVER_CONF))
    return conf
