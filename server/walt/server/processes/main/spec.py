from pathlib import Path

from walt.common.config import load_conf

SERVER_SPEC_PATH = Path("/etc/walt/server.spec")
SERVER_SPEC = None


def get_server_spec():
    global SERVER_SPEC
    if SERVER_SPEC is None:
        SERVER_SPEC = load_conf(SERVER_SPEC_PATH, optional=True)
        if SERVER_SPEC is None:
            SERVER_SPEC = {}
    return SERVER_SPEC


def reload_server_spec():
    global SERVER_SPEC
    SERVER_SPEC = None
    get_server_spec()


def get_server_features():
    return set(get_server_spec().get("features", []))


def server_has_feature(feature):
    return feature in get_server_features()
