#!/usr/bin/env python3
from pathlib import Path
from ipaddress import ip_network
import sys, json, subprocess, time
from walt.common.apilink import ServerAPILink

sys.stdout = open('/tmp/server-conf.stdout', 'w')
sys.stderr = open('/tmp/server-conf.stderr', 'w')

t0 = time.time()
WALT_IP_CIDR = "192.168.204.1/22"

def log_event(evt):
    print(f'{time.time()-t0} {evt}')

def run_cmd(cmd):
    subprocess.run(cmd, shell=True)

with open(sys.argv[1], 'r') as f:
    job_conf = json.load(f)

log_event('updating conf')

# update /etc/network/interfaces
network_interfaces_file = Path("/etc/network/interfaces")
network_interfaces = network_interfaces_file.read_text()
network_interfaces += """

# walt network interface configuration
# => this will just apply config given in file
#    /etc/walt/server.conf

auto walt-net

iface walt-net inet manual
    up walt-net-config up
    down walt-net-config down
"""
network_interfaces_file.write_text(network_interfaces)

# write /etc/walt/server.conf
server_conf_file = Path("/etc/walt/server.conf")
server_conf = """
{
    # network configuration
    # ---------------------
    "network": {
        # platform network
        "walt-net": {
            "raw-device": "__WALT_NET_INTF__",
            "ip": "__WALT_IP_CIDR__"
        }
    }
}
"""
server_conf = server_conf.replace(
            '__WALT_NET_INTF__', job_conf['walt_netcard_name'])
server_conf = server_conf.replace(
            '__WALT_IP_CIDR__', WALT_IP_CIDR)
server_conf_file.write_text(server_conf)

# configure walt-net interface
log_event('ifup walt-net')
run_cmd('ifup walt-net')

# enable and start walt server daemon
log_event('enable & start walt-server')
run_cmd('systemctl enable walt-server')
run_cmd('systemctl start walt-server')

# populate the database with node information
# (useful to have the same node names in walt and g5k)
walt_subnet = ip_network(WALT_IP_CIDR, strict=False)
free_ips = list(walt_subnet.hosts())
free_ips.pop(0) # first address is for the server
with ServerAPILink('localhost', 'SSAPI') as server:
    for name, mac in job_conf['nodes']:
        # simulate a DHCP request from the node (=> create it in db)
        ip = str(free_ips.pop(0))
        log_event(f'server.register_device() {ip} {mac} {name}')
        server.register_device('walt.node.pc-x86-64', '', ip, mac, name)

# restore a .waltrc file with just the server hostname (as localhost)
# note: up to now it contained fake credentials to allow
# the 'walt device rename' command above.
log_event('restore /root/.waltrc')
run_cmd('cp /root/.waltrc.no-user /root/.waltrc')

log_event('done')
