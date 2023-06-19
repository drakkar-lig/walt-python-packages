# this is the code called by tool
# walt-g5k-deploy-helper
import json
import sys
import time
import traceback
from getpass import getuser

import requests
from pkg_resources import resource_string
from urllib3.exceptions import InsecureRequestWarning
from walt.client.config import conf, save_config
from walt.client.g5k.deploy.status import (
    get_deployment_status,
    log_status_change,
    record_main_job_ending,
    record_main_job_startup,
)
from walt.client.g5k.reboot import reboot_nodes
from walt.client.g5k.tools import (
    oarstat,
    printed_date_from_ts,
    run_cmd_on_site,
    set_vlan,
)
from walt.client.link import ClientToServerLink

DEFAULT_IMAGE_NAME = "pc-x86-64-default"

# Suppress warning about requests not verifying remote certificate
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def analyse_g5k_resources(info, site):
    log_status_change(
        info,
        "resources.detection." + site,
        "Detecting targeted resources",
        verbose=True,
    )
    analyse_g5k_nodes(info, site)
    if site == info["vlan"]["site"]:
        output = run_cmd_on_site(info, site, ["kavlan", "-V"], True)
        try:
            info["vlan"]["vlan_id"] = int(output)
        except Exception:
            raise Exception(f"G5K vlan reservation failed at {site}!")


def yield_enabled_netcards(node_hostname):
    node_info = get_node_info(node_hostname)
    for netcard_info in node_info["network_adapters"]:
        if not netcard_info["enabled"]:
            continue
        yield netcard_info


# Usually the main netcard is the one recorded with device="eth0" in the API
# and the secondary netcard (used for walt-net network on walt server) has
# device="eth1". However, some clusters may have disabled devices (e.g. hercule
# cluster at Lyon), which cause this numbering to be shifted.
def main_netcard(node_hostname):
    for netcard in yield_enabled_netcards(node_hostname):
        if netcard.get("network_address", "") == node_hostname:
            return netcard


def secondary_netcard(node_hostname):
    for netcard in yield_enabled_netcards(node_hostname):
        if netcard.get("network_address", "") != node_hostname:
            return netcard


def analyse_g5k_nodes(info, site):
    # this is equivalent to:
    # $ oarstat -p | oarprint host -P eth_count,host -f -
    oarstat_output = run_cmd_on_site(info, site, ["oarstat", "-p"], True)
    output = run_cmd_on_site(
        info, site, "oarprint host -P eth_count,host -f -".split(), input=oarstat_output
    )
    walt_nodes = {}
    for line in output.strip().split("\n"):
        if line.strip() == "":
            continue
        eth_count, host = line.split()
        if (
            info["server"]["site"] == site
            and info["server"].get("host") is None
            and int(eth_count) > 1
        ):
            info["server"]["host"] = host
        else:
            netcard = main_netcard(host)
            walt_nodes[host] = dict(walt_name=host.split(".")[0], mac=netcard["mac"])
    info["sites"][site]["nodes"] = walt_nodes


def get_node_info(node_hostname):
    node_nodomain, site = node_hostname.split(".")[:2]
    node_cluster = node_nodomain.rsplit("-", maxsplit=1)[0]
    node_api = (
            f"https://api.grid5000.fr/sid/sites/{site}/"
            f"clusters/{node_cluster}/nodes/{node_nodomain}.json"
    )
    resp = requests.get(node_api, verify=False)
    return resp.json()


def verify_vlan_rights(info):
    vlan_id = info["vlan"]["vlan_id"]
    user = getuser()
    for site in info["sites"]:
        url = f"https://api.grid5000.fr/sid/sites/{site}/vlans/{vlan_id}/users"
        resp = requests.get(url, verify=False).json()
        users = set(item["uid"] for item in resp["items"])
        if user not in users:
            raise Exception(
                f"Error: G5K failed to propagate VLAN {vlan_id} access right for user"
                f" {user} at {site}."
            )


def configure_server(info, walt_netcard_name):
    server_node = info["server"]["host"]
    nodes_info = []
    for site, site_info in info["sites"].items():
        for node_info in site_info["nodes"].values():
            nodes_info.append((node_info["walt_name"], node_info["mac"]))
    json_conf = json.dumps(
        {"walt_netcard_name": walt_netcard_name, "nodes": nodes_info}
    )
    server_site = info["server"]["site"]
    # write this conf to the server
    run_cmd_on_site(
        info,
        server_site,
        f"ssh root@{server_node} tee /tmp/g5k.json".split(),
        input=json_conf,
    )
    # get conf script and send it to the server
    script_content = resource_string(__name__, "remote-server-conf.py")
    run_cmd_on_site(
        info,
        server_site,
        f"ssh root@{server_node} tee /tmp/remote-server-conf.py".split(),
        input=script_content.decode("UTF-8"),
    )
    # execute conf script
    cmd = (f"ssh root@{server_node}"
           " walt-python3 /tmp/remote-server-conf.py /tmp/g5k.json")
    run_cmd_on_site(
        info,
        server_site,
        cmd.split(),
    )


# since this script is called from the main job, running on
# the site where walt server will be deployed, we know the job is
# already running at this site.
# this function will wait for other sites to be running too.
def wait_for_other_jobs(info):
    main_job_site = info["server"]["site"]
    while True:
        max_start_time = 0
        waiting_sites = []
        for site in info["sites"]:
            if site == main_job_site:
                continue
            job_stat = oarstat(info, site)
            if job_stat is None:
                raise Exception(f"G5K failed to reserve the job at {site}!")
            if job_stat["state"] != "Running":
                waiting_sites.append(site)
                scheduled_start = job_stat.get("scheduledStart")
                if scheduled_start is None:
                    raise Exception(f"G5K failed to reserve the job at {site}!")
                max_start_time = max(max_start_time, scheduled_start)
        if len(waiting_sites) == 0:
            break
        status = "jobs.others.waiting"
        comment = "Waiting for the jobs to run on site(s): " + ", ".join(
            sorted(waiting_sites)
        )
        log_status_change(info, status, comment, verbose=True)
        time.sleep(5)


class LoggerBusyIndicator:
    def __init__(self, info, status, default_label):
        self._info = info
        self._status = status
        self._default_label = default_label

    def set_label(self, label):
        print(label)
        log_status_change(self._info, self._status, label)

    def set_default_label(self):
        self.set_label(self._default_label)

    # ignore other calls
    def __getattr__(self, attr):
        return lambda *args: None


def run_deployment_tasks(info):
    # since helper was called, we know the job is ready at the site where walt server
    # must be deployed. start deploying server asap because it will take time.
    server_site = info["server"]["site"]
    analyse_g5k_resources(info, server_site)
    server_node = info["server"]["host"]
    walt_netcard = secondary_netcard(server_node)
    # -- deploy server
    log_status_change(
        info,
        "server.deploy",
        f"Deploying walt server on node {server_node}",
        verbose=True,
    )
    env_file = info["server"]["g5k_env_file"]
    run_cmd_on_site(
        info, server_site, f"kadeploy3 -m {server_node} -a {env_file} -k".split()
    )
    # -- wait for secondary jobs at other sites (they should be ready now...)
    log_status_change(
        info, "jobs.others.checking", "Checking secondary jobs are ready", verbose=True
    )
    wait_for_other_jobs(info)
    # -- detect g5k resources at those other sites
    for site in info["sites"]:
        if site == server_site:
            continue
        analyse_g5k_resources(info, site)
    verify_vlan_rights(info)
    # -- configure server
    log_status_change(info, "server.walt.conf", "Configuring walt server", verbose=True)
    configure_server(info, walt_netcard["name"])
    # -- update vlan conf
    vlan_id = info["vlan"]["vlan_id"]
    vlan_site = info["vlan"]["site"]
    log_status_change(
        info,
        "vlan.conf.dhcp",
        f"Removing default DHCP service on VLAN {vlan_id}",
        verbose=True,
    )
    run_cmd_on_site(info, vlan_site, f"kavlan -d -i {vlan_id}".split(), True)
    log_status_change(
        info,
        "vlan.conf.server",
        f"Attaching walt server secondary interface to VLAN {vlan_id}",
        verbose=True,
    )
    set_vlan(info, server_site, vlan_id, walt_netcard["network_address"])
    log_status_change(
        info, "vlan.conf.nodes", f"Attaching walt nodes to VLAN {vlan_id}", verbose=True
    )
    for site, site_info in info["sites"].items():
        if len(site_info["nodes"]) == 0:
            continue
        nodes = list(site_info["nodes"])
        set_vlan(info, site, vlan_id, *nodes)
    # -- update .walt/config
    log_status_change(info, "client.conf", "Updating $HOME/.walt/config", verbose=True)
    conf.walt.server = server_node
    # this walt server is dedicated to the calling user
    # no need to manage multiple usernames on server side
    conf.walt.username = "walt-g5k"
    save_config()
    # -- associate nodes to the calling user
    busy_indicator = LoggerBusyIndicator(
        info, "nodes.set_owner", "Associating nodes to the calling user"
    )
    with ClientToServerLink(do_checks=False, busy_indicator=busy_indicator) as server:
        server.set_image("all-nodes", DEFAULT_IMAGE_NAME)
    # -- reboot nodes
    log_status_change(info, "nodes.reboot", "Rebooting walt nodes", verbose=True)
    all_nodes = sum(
        (list(site_info["nodes"]) for site_info in info["sites"].values()), []
    )
    rebooted_node_names, reboot_errors = reboot_nodes(info, all_nodes)
    if len(reboot_errors) > 0:
        print("Reboot failed!")
        for node_name, err in reboot_errors.items():
            print("{node_name}: {err}")
        raise Exception("Reboot failed!")
    # -- wait for nodes
    busy_indicator = LoggerBusyIndicator(
        info, "nodes.waiting", "Waiting for first bootup of nodes"
    )
    with ClientToServerLink(do_checks=False, busy_indicator=busy_indicator) as server:
        server.wait_for_nodes("all-nodes")
    log_status_change(info, "ready", "Ending WalT platform deployment")
    print("Ready!")
    sys.stdout.flush()


def handle_failure(info, e):
    # kill secondary jobs
    for site in info["sites"]:
        if site == info["server"]["site"]:  # current site
            continue
        job_id = info["sites"][site]["job_id"]
        args = ["oardel", job_id]
        run_cmd_on_site(info, site, args, err_out=False)
    # print exception to log
    traceback.print_exc()
    # record ending
    sys.stdout.flush()
    sys.stderr.flush()
    time.sleep(0.2)
    record_main_job_ending(info, e)


def print_banner(f, msg):
    print(file=f)
    print("-" * len(msg), file=f)
    print(msg, file=f)
    f.flush()


class StreamSaver:
    def __init__(self, info, stream_name):
        logs_dir = info["logs_dir"]
        self._stream = open(f"{logs_dir}/deploy.{stream_name}", "w")
        self._orig_stream = getattr(sys, "__" + stream_name + "__")

    def write(self, s):
        self._stream.write(s)
        return self._orig_stream.write(s)

    def flush(self):
        self._stream.flush()
        self._orig_stream.flush()

    @property
    def encoding(self):
        return self._orig_stream.encoding


# Note: this helper program is called when the g5k "main" job starts to run.
# The main job is the one running at the site where the walt server will be deployed.
# This job connects back to the site where 'walt g5k deploy' command was run, and
# runs this script there.
# This script should then remain alive to maintain the main job alive.
def run():
    now = time.time()
    deployment_id = sys.argv[1]
    info = get_deployment_status(deployment_id)
    sys.stdout = StreamSaver(info, "stdout")
    sys.stderr = StreamSaver(info, "stderr")
    printed_now = printed_date_from_ts(now)
    first_msg = f"{printed_now}: WalT platform deployment helper started"
    print_banner(sys.stdout, first_msg)
    print_banner(sys.stderr, first_msg)
    record_main_job_startup(info)
    try:
        run_deployment_tasks(info)
    except Exception as e:
        handle_failure(info, e)
        return
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
    # remain alive
    time.sleep(info["end_date"] + 1 - time.time())
