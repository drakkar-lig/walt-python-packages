#!/usr/bin/env walt-python3
import json
import subprocess
import sys
import time
from ipaddress import ip_address, ip_network
from pathlib import Path

from walt.common.apilink import ServerAPILink

sys.stdout = open("/tmp/server-conf.stdout", "w")
sys.stderr = open("/tmp/server-conf.stderr", "w")

t0 = time.time()
WALT_SERVER_IP = "192.168.204.1"
WALT_IP_CIDR = f"{WALT_SERVER_IP}/22"


def log_event(evt):
    print(f"{time.time()-t0} {evt}")


def run_cmd(cmd):
    subprocess.run(cmd, shell=True)


with open(sys.argv[1], "r") as f:
    job_conf = json.load(f)

log_event("updating conf")

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
server_conf = server_conf.replace("__WALT_NET_INTF__", job_conf["walt_netcard_name"])
server_conf = server_conf.replace("__WALT_IP_CIDR__", WALT_IP_CIDR)
server_conf_file.write_text(server_conf)

# run walt-server-setup to have all walt services ready
log_event("run walt-server-setup")
run_cmd("walt-server-setup")

# populate the database with node information
# (useful to have the same node names in walt and g5k)
walt_subnet = ip_network(WALT_IP_CIDR, strict=False)
free_ips = set(walt_subnet.hosts())
free_ips.discard(ip_address(WALT_SERVER_IP))
free_ips = sorted(free_ips)
with ServerAPILink("localhost", "SSAPI") as server:
    for name, mac in job_conf["nodes"]:
        # simulate a DHCP request from the node (=> create it in db)
        ip = str(free_ips.pop(0))
        log_event(f"server.register_device() {ip} {mac} {name}")
        server.register_device("walt.node.pc-x86-64", "", ip, mac, name)

# restore a .walt/config file with just the server hostname (as localhost)
# note: up to now it contained fake credentials to allow
# the 'walt device rename' command above.
log_event("restore /root/.walt/config")
run_cmd("cp /root/.walt/config.no-user /root/.walt/config")

log_event("done")
