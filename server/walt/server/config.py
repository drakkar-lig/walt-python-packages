"""Server configuration management."""
import copy
import sys
from ipaddress import ip_network
from pathlib import Path

from walt.common.config import load_conf

SERVER_CONF = Path("/etc/walt/server.conf")
DEFAULT_CONF = {
    "services": {
        "nfsd": {
            "service-name": "nfs-kernel-server.service",
        },
    },
    "registries": [
        {
            "label": "hub",
            "api": "docker-hub",
            "description": "Public registry at hub.docker.com",
        }
    ],
}


def check_ip_network(ip_net):
    try:
        ip_network(str(ip_net), strict=False)
    except Exception:
        return False
    return True


def check_conf():
    conf = load_conf(SERVER_CONF)
    if (
        "network" not in conf
        or "walt-net" not in conf["network"]
        or "ip" not in conf["network"]["walt-net"]
        or not check_ip_network(conf["network"]["walt-net"]["ip"])
    ):
        print(f"Invalid configuration at '{SERVER_CONF}'.", file=sys.stderr)
        print("Run 'walt-server-setup --edit-conf' to fix it.", file=sys.stderr)
        raise Exception(f"Invalid configuration at '{SERVER_CONF}'.")


def sanitize_conf(conf):
    if "vpn" in conf:
        vpnconf = conf["vpn"]
        if "enabled" in vpnconf:
            if vpnconf["enabled"]:
                attrs = set((
                    'enabled',
                    'ssh-entrypoint',
                    'http-entrypoint',
                    'boot-mode'))
                if set(vpnconf.keys()) != attrs:
                    # invalid, discard
                    conf["vpn"] = {"enabled": False}
            else:
                # enabled=No but other VPN conf attributes specified,
                # auto fix by removing other attributes
                if len(vpnconf) > 1:
                    conf["vpn"] = {"enabled": False}
        else:
            attrs = set((
                'ssh-entrypoint',
                'http-entrypoint',
                'boot-mode'))
            if set(vpnconf.keys()) == attrs:
                # early VPN deployments did not have the "enabled" attr
                # but this one seemed to be configured.
                # add the "enabled" attr as 1st attr.
                prev_vpnconf = conf["vpn"]
                conf["vpn"] = {"enabled": True}
                conf["vpn"].update(prev_vpnconf)
            else:
                # empty or invalid, discard
                conf["vpn"] = {"enabled": False}
    else:
        conf["vpn"] = {"enabled": False}


def get_conf():
    """Load the server configuration"""
    conf = copy.copy(DEFAULT_CONF)
    conf.update(load_conf(SERVER_CONF))
    sanitize_conf(conf)
    return conf


def cleanup_defaults(conf):
    """Discard items rarely configured and having default values"""
    clean_conf = {k: v for (k, v) in conf.items()}
    if "services" in conf and conf["services"] == DEFAULT_CONF["services"]:
        del clean_conf["services"]
    return clean_conf
