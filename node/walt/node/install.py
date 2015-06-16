#!/usr/bin/env python
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

USAGE = "usage: %(prog)s <server_ip>\n"

def run():
    if len(argv) < 2:
        stderr.write(USAGE % dict(prog=argv[0]))
        exit()
    env = dict(server_ip = argv[1])
    with open(NTP_CONF_PATH, 'w') as f:
        f.write(NTP_CONF % env)
    with open(SYSTEMD_SERVICE_PATH, 'w') as f:
        f.write(SYSTEMD_SERVICE_CONF % env)

if __name__ == "__main__":
    run()

