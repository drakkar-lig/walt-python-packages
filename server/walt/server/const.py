SETUP_INTF = "eth0"
WALT_INTF = "walt-net"
EXTERN_INTF = "walt-out"
DEFAULT_IMAGE = "default"
SNMP_TIMEOUT = 3
WALT_DBNAME = "walt"
WALT_DBUSER = "root"
SSH_COMMAND = (
    "ssh -o PreferredAuthentications=publickey -o StrictHostKeyChecking=no -o"
    " ConnectTimeout=10 -o ServerAliveInterval=5"
)
WALT_NODE_NET_SERVICE_PORT = 12346
SERVER_SNMP_CONF = dict(version=2, community="private")
UNIX_SERVER_SOCK_PATH = "/var/run/walt/walt-server/walt-server.socket"
