from walt.common.tools import read_json

SERVER_CONF='/etc/walt/server.conf'

def get_conf():
    return read_json(SERVER_CONF)
