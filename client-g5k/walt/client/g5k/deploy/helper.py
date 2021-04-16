# this is the code called by tool
# walt-g5k-deploy-helper
import requests, subprocess, sys, time, json, atexit
from walt.common.formatting import human_readable_delay
from walt.client.g5k.tools import Cmd, run_cmd_on_site, oarstat, printed_date_from_ts
from walt.client.g5k.deploy.status import get_deployment_status, log_status_change, \
                                  record_main_job_startup, record_main_job_ending
from walt.client.config import save_config, get_config_from_file, set_conf
from walt.client.link import ClientToServerLink
from urllib3.exceptions import InsecureRequestWarning

# Suppress warning about requests not verifying remote certificate
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

def update_nodes(info):
    for site in info['sites'].keys():
        # this is equivalent to:
        # $ oarstat -p | oarprint host -P eth_count,host -f -
        oarstat_output = run_cmd_on_site(info, site, [ 'oarstat', '-p' ], True)
        output = run_cmd_on_site(info, site,
                    'oarprint host -P eth_count,host -f -'.split(),
                    input = oarstat_output)
        walt_nodes = {}
        for line in output.strip().split('\n'):
            if line.strip() == '':
                continue
            eth_count, host = line.split()
            if info['server']['site'] == site and \
               info['server'].get('host') is None and \
               int(eth_count) > 1:
                info['server']['host'] = host
            else:
                node_info = get_node_info(host)
                walt_nodes[host] = dict(
                    walt_name = host.split('.')[0],
                    mac = node_info['network_adapters'][0]['mac']
                )
        info['sites'][site]['nodes'] = walt_nodes

def update_vlan_id(info):
    vlan_site = info['vlan']['site']
    info['vlan']['vlan_id'] = int(
        run_cmd_on_site(info, vlan_site, [ 'kavlan', '-V' ], True))

def get_node_info(node_hostname):
    node_nodomain, site = node_hostname.split('.')[:2]
    node_cluster = node_nodomain.rsplit('-', maxsplit=1)[0]
    node_api = f'https://api.grid5000.fr/sid/sites/{site}/clusters/{node_cluster}/nodes/{node_nodomain}.json'
    resp = requests.get(node_api, verify=False)
    return resp.json()

def send_json_conf_to_server(info):
    server_node = info['server']['host']
    server_info = get_node_info(server_node)
    server_eth1_name = server_info['network_adapters'][1]['name']
    nodes_info = []
    for site, site_info in info['sites'].items():
        for node_info in site_info['nodes'].values():
            nodes_info.append((node_info['walt_name'], node_info['mac']))
    json_conf = json.dumps({
        'server_eth1_name': server_eth1_name,
        'nodes': nodes_info
    })
    # write this conf to the server
    run_cmd_on_site(info, info['server']['site'],
                f'ssh root@{server_node} tee /tmp/g5k.json'.split(),
                input=json_conf)

# since this script is called from the main job, running on
# the site where walt server will be deployed, we know the job is
# already running at this site.
# this function will wait for other sites to be running too.
def wait_for_other_jobs(info):
    main_job_site = info['server']['site']
    while True:
        max_start_time = 0
        waiting_sites = []
        for site in info['sites']:
            if site == main_job_site:
                continue
            job_stat = oarstat(info, site)
            if job_stat['state'] != 'Running':
                waiting_sites.append(site)
                max_start_time = max(max_start_time, job_stat['scheduledStart'])
        if len(waiting_sites) == 0:
            break
        status  = 'jobs.others.waiting'
        comment = 'Waiting for the jobs to run on site(s): ' + \
                  ', '.join(sorted(waiting_sites))
        log_status_change(info, status, comment, verbose = True)
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

def run_deployment_tasks():
    info = get_deployment_status()
    log_status_change(info, 'jobs.others.waiting', "Waiting for secondary jobs", verbose = True)
    wait_for_other_jobs(info)
    log_status_change(info, 'resources.detection', "Detecting targeted resources", verbose = True)
    update_vlan_id(info)
    vlan_id = info['vlan']['vlan_id']
    vlan_site = info['vlan']['site']
    update_nodes(info)
    server_site = info['server']['site']
    server_node = info['server']['host']
    server_node_eth1 = '-eth1.'.join(server_node.split('.',maxsplit=1))
    log_status_change(info, 'vlan.conf', f'Removing default DHCP service on VLAN {vlan_id}', verbose = True)
    run_cmd_on_site(info, vlan_site, f'kavlan -d -i {vlan_id}'.split(), True)
    # deploy server
    log_status_change(info, 'server.deploy', f'Deploying walt server on node {server_node} (expect ~5min)', verbose = True)
    env_file = info['server']['g5k_env_file']
    run_cmd_on_site(info, server_site,
                f'kadeploy3 -m {server_node} -a {env_file}'.split())
    log_status_change(info, 'server.network.conf', f'Attaching walt server secondary interface to VLAN {vlan_id}', verbose = True)
    run_cmd_on_site(info, server_site,
                f'kavlan -s -i {vlan_id} -m {server_node_eth1}'.split(), True)
    # configure server
    log_status_change(info, 'server.walt.conf', 'Configuring walt server', verbose = True)
    send_json_conf_to_server(info)
    run_cmd_on_site(info, server_site,
                f'ssh root@{server_node} /root/walt-server-setup.py /tmp/g5k.json'.split())
    # update server in .waltrc
    log_status_change(info, 'client.conf', 'Updating $HOME/.waltrc', verbose = True)
    conf = get_config_from_file()
    conf['server'] = server_node
    save_config(conf)
    # boot walt nodes
    log_status_change(info, 'nodes.network.conf', f'Attaching walt nodes to VLAN {vlan_id} and rebooting them', verbose = True)
    for site, site_info in info['sites'].items():
        for node in site_info['nodes']:
            run_cmd_on_site(info, site, f'kavlan -s -i {vlan_id} -m {node}'.split(), True)
            run_cmd_on_site(info, site, f'kareboot3 --no-wait -l hard -m {node}'.split())
    # note: waiting for nodes may require user credentials to be available,
    # and they may not be present yet in .waltrc, so set temporary ones.
    conf['username'], conf['password'] = 'anonymous', 'none'
    set_conf(conf)  # temporary conf, not saved in .waltrc
    busy_indicator = LoggerBusyIndicator(info, 'nodes.waiting',
                                         'Waiting for first bootup of nodes')
    with ClientToServerLink(do_checks=False, busy_indicator=busy_indicator) as server:
        server.wait_for_nodes('all-nodes')
    log_status_change(info, 'ready', 'Ending WalT platform deployment')
    print('Ready!')
    sys.stdout.flush()

def on_ending():
    # kill secondary jobs
    info = get_deployment_status()
    if info is not None:
        for site in info['sites']:
            if site == info['server']['site']:  # current site
                continue
            job_id = info['sites'][site]['job_id']
            args = [ 'oardel', job_id ]
            run_cmd_on_site(info, site, args, err_out=False)
    # record ending
    record_main_job_ending()

# Note: this helper program is called when the g5k "main" job starts to run.
# The main job is the one running at the site where the walt server will be deployed.
# This job connects back to the site where 'walt g5k deploy' command was run, and
# runs this script there.
# This script should then remain alive to maintain the main job alive.
def run():
    now = time.time()
    print()
    first_msg = "%s: WalT platform deployment helper started." % printed_date_from_ts(now)
    print('-'*len(first_msg))
    print(first_msg)
    sys.stdout.flush()
    record_main_job_startup()
    atexit.register(on_ending)
    run_deployment_tasks()
    # remain alive
    info = get_deployment_status()
    time.sleep(info['end_date'] +1 - time.time())
