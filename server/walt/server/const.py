SETUP_INTF = "eth0"
WALT_INTF = "walt-net"
EXTERN_INTF = "walt-out"
DEFAULT_IMAGE = "default"
SNMP_TIMEOUT = 3
WALT_DBNAME = "walt"
WALT_DBUSER = "root"
SSH_NODE_COMMAND = (
    "ssh -o PreferredAuthentications=publickey "
        "-o UserKnownHostsFile=/var/lib/walt/ssh/known_hosts.nodes "
        "-o HostKeyAlias=walt.node "
        "-o ConnectTimeout=10 "
        "-o ServerAliveInterval=5 "
)
SSH_DEVICE_COMMAND = "walt-device-ssh"
WALT_NODE_NET_SERVICE_PORT = 12346
SERVER_SNMP_CONF = dict(version=2, community="private")
UNIX_SERVER_SOCK_PATH = "/var/run/walt/walt-server/walt-server.socket"
PODMAN_API_SOCK_PATH = "/run/walt/podman/podman.socket"
