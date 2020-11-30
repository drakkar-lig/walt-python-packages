from walt.common.tools import read_json

SERVER_SPEC_PATH = '/etc/walt/server.spec'
SERVER_SPEC = None

def get_server_spec():
    global SERVER_SPEC
    if SERVER_SPEC is None:
        try:
            SERVER_SPEC = read_json(SERVER_SPEC_PATH)
        except:
            sys.stderr.write('Failed to parse /etc/walt/server.spec (should be json).')
    return SERVER_SPEC

def reload_server_spec():
    global SERVER_SPEC
    SERVER_SPEC = None
    get_server_spec()

def get_server_features():
    return set(get_server_spec().get('features', []))

def server_has_feature(feature):
    return feature in get_server_features()
