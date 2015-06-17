#!/usr/bin/env python
import os
from sys import stdout, stderr, argv, exit

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
NODE_DSA_KEYPAIR = dict(
    private_key = """\
-----BEGIN DSA PRIVATE KEY-----
MIIBvQIBAAKBgQDlqf9HzsAhiWuCKK7vO73y0BeUeIxQi27pLnpBuevTyycR8QA+
Ayn7lmw2WDML9DyhWSDh3954aSOpmtCG/G9i6OQIhfvPtnbGbL7jCph5KNDeNTHh
D3ME7Yg4Mx4rxZNfNGUKnRdMjV5bPlcwrdTki8vwMFFYD5eTEfrJUSbIJwIVAMoM
VowNNHgwdR6SQ90kXdNbU+O/AoGBANzB+MXSxGMK7F+7edPpG5vv6lkjt8fhERMa
jfiEH3EMoNIB/WNv6iKiEn9fBEc6U+38L4z6n1KrXhgKBt3c5pHoce41TEfThV1y
M/unkmU3YWgJcODj92B35mTNrcCcxrZNYiVuwqUyEaU50hAyKsGB2h8p7QN8K4zY
OO377uEPAoGBANCPhPblyuuCDXCQ/td8QHaesENhiOLGc+KlEwEzTaSZ833rt1II
c18yGt9C86cxW4drWQNlGiBivicrNv82s0vlDARziYeGbQlpIO2x3SWWJDvlVbmw
xiVcdUeMwe3Xnusz0aIEBicJM/FC2DM6Yogg0o4nk2SDkhYoUD+KBNb4AhUArld+
wvxMEdvTpj6gkC+FaXL+Rmw=
-----END DSA PRIVATE KEY-----
""",
    private_key_path = '/etc/ssh/ssh_host_dsa_key',
    public_key = """\
ssh-dss AAAAB3NzaC1kc3MAAACBAOWp/0fOwCGJa4Ioru87vfLQF5R4jFCLbukuekG569PLJxHxAD4DKfuWbDZYMwv0PKFZIOHf3nhpI6ma0Ib8b2Lo5AiF+8+2dsZsvuMKmHko0N41MeEPcwTtiDgzHivFk180ZQqdF0yNXls+VzCt1OSLy/AwUVgPl5MR+slRJsgnAAAAFQDKDFaMDTR4MHUekkPdJF3TW1PjvwAAAIEA3MH4xdLEYwrsX7t50+kbm+/qWSO3x+ERExqN+IQfcQyg0gH9Y2/qIqISf18ERzpT7fwvjPqfUqteGAoG3dzmkehx7jVMR9OFXXIz+6eSZTdhaAlw4OP3YHfmZM2twJzGtk1iJW7CpTIRpTnSEDIqwYHaHyntA3wrjNg47fvu4Q8AAACBANCPhPblyuuCDXCQ/td8QHaesENhiOLGc+KlEwEzTaSZ833rt1IIc18yGt9C86cxW4drWQNlGiBivicrNv82s0vlDARziYeGbQlpIO2x3SWWJDvlVbmwxiVcdUeMwe3Xnusz0aIEBicJM/FC2DM6Yogg0o4nk2SDkhYoUD+KBNb4 root@rpi-ED
""",
    public_key_path = '/etc/ssh/ssh_host_dsa_key.pub'
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
    with open(NODE_DSA_KEYPAIR['private_key_path'], 'w') as f:
        f.write(NODE_DSA_KEYPAIR['private_key'])
    with open(NODE_DSA_KEYPAIR['public_key_path'], 'w') as f:
        f.write(NODE_DSA_KEYPAIR['public_key'])
    if not os.path.exists(os.path.dirname(AUTHORIZED_KEYS_PATH)):
        os.makedirs(os.path.dirname(AUTHORIZED_KEYS_PATH))
    with open(AUTHORIZED_KEYS_PATH, 'w') as f:
        f.write(server_pubkey)

if __name__ == "__main__":
    run()

