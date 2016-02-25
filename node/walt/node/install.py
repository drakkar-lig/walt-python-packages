#!/usr/bin/env python
import os
from sys import stdout, stderr, argv, exit
from walt.node.spec import enable_matching_features

NTP_CONF_PATH = "/etc/ntp.conf"
NTP_CONF = """
driftfile /var/lib/ntp/ntp.drift

statistics loopstats peerstats clockstats
filegen loopstats file loopstats type day enable
filegen peerstats file peerstats type day enable
filegen clockstats file clockstats type day enable

server %(server_ip)s

restrict -4 default kod notrap nomodify nopeer noquery
restrict -6 default kod notrap nomodify nopeer noquery

restrict 127.0.0.1
restrict ::1
"""

SYSTEMD_SERVICE_PATH = "/etc/systemd/system/walt-node.service"
SYSTEMD_SERVICE_CONF = """
# walt-node - WalT platform node daemon
#
# The WalT platform provides a lightweight distributed testbed for
# sensor networks, distributed protocols, distributed data
# management.

[Unit]
Description=WalT node daemon
# start the daemon after ssh is started.
# this ensures that as soon as the node registers, as part of the
# daemon startup process, we know we can reach it through ssh.
After=ssh.service

[Service]
Type=simple
EnvironmentFile=-/etc/default/walt-node
EnvironmentFile=-/etc/sysconfig/walt-node
ExecStart=/usr/local/bin/walt-node-daemon $DAEMON_ARGS
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""

# when using walt, nodes often get new operating system
# images, and usually each of these images has a new
# authentication key.
# this causes annoyance when using ssh to connect from the
# server to a node.
# we do not really need to secure access to nodes, since
# they are very temporary environments, and since the walt
# network is in a dedicated, separated vlan.
# thus, when mounting an image, we will overwrite its
# authentication key with the following one, which will
# remain constant.
NODE_ECDSA_KEYPAIR = dict(
    private_key = """\
-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIDWsENxcRUkFkTi/gqNog7XbEUgJqXto4LBmR912mESMoAoGCCqGSM49
AwEHoUQDQgAE219o+OBl5qGa6iYOkHlCBbdPZs20vvIQf+bp0kIwI4Lmdq79bTTz
REHbx9/LKRGRn8z2QMq3EY9V/stQpHc68w==
-----END EC PRIVATE KEY-----
""",
    private_key_path = '/etc/ssh/ssh_host_ecdsa_key',
    public_key = """\
ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBNtfaPjgZeahmuomDpB5QgW3T2bNtL7yEH/m6dJCMCOC5nau/W0080RB28ffyykRkZ/M9kDKtxGPVf7LUKR3OvM= root@rpi_ED
""",
    public_key_path = '/etc/ssh/ssh_host_ecdsa_key.pub'
)

AUTHORIZED_KEYS_PATH = '/root/.ssh/authorized_keys'

USAGE = '''usage: %(prog)s <server_ip> "<server_public_key>"\n'''

def run():
    if len(argv) < 3:
        stderr.write(USAGE % dict(prog=argv[0]))
        exit()
    env = dict(server_ip = argv[1])
    server_pubkey = argv[2]
    with open(NTP_CONF_PATH, 'w') as f:
        f.write(NTP_CONF % env)
    with open(SYSTEMD_SERVICE_PATH, 'w') as f:
        f.write(SYSTEMD_SERVICE_CONF % env)
    with open(NODE_ECDSA_KEYPAIR['private_key_path'], 'w') as f:
        f.write(NODE_ECDSA_KEYPAIR['private_key'])
    with open(NODE_ECDSA_KEYPAIR['public_key_path'], 'w') as f:
        f.write(NODE_ECDSA_KEYPAIR['public_key'])
    if not os.path.exists(os.path.dirname(AUTHORIZED_KEYS_PATH)):
        os.makedirs(os.path.dirname(AUTHORIZED_KEYS_PATH))
    with open(AUTHORIZED_KEYS_PATH, 'w') as f:
        f.write(server_pubkey)
    enable_matching_features()

if __name__ == "__main__":
    run()

