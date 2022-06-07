"""Server configuration management."""
import sys, copy

from pathlib import Path
from ipaddress import ip_network
from walt.common.config import load_conf

SERVER_CONF = Path('/etc/walt/server.conf')
DEFAULT_CONF = {
    "services": {
        "nfsd": {
            "service-name": "nfs-kernel-server.service",
        },
    }
}

def check_ip_network(ip_net):
    try:
        ip_network(str(ip_net), strict=False)
    except:
        return False
    return True

def check_conf():
    conf = load_conf(SERVER_CONF)
    if 'network' not in conf or \
       'walt-net' not in conf['network'] or \
       'ip' not in conf['network']['walt-net'] or \
       not check_ip_network(conf['network']['walt-net']['ip']):
        print(f"Invalid configuration at '{SERVER_CONF}'.", file=sys.stderr)
        print(f"Run 'walt-server-setup --edit-conf' to fix it.", file=sys.stderr)
        raise Exception(f"Invalid configuration at '{SERVER_CONF}'.")

def get_conf():
    """Load the server configuration"""
    conf = copy.copy(DEFAULT_CONF)
    conf.update(load_conf(SERVER_CONF))
    return conf
