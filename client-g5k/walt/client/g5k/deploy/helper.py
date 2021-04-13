# this is the code called by tool
# walt-g5k-deploy-helper
import requests, subprocess, sys, time, json
from walt.common.formatting import human_readable_delay
from walt.client.g5k.tools import Cmd, run_cmd_on_site, oarstat
from walt.client.g5k.deploy.status import get_deployment_status, log_status_change
from walt.client.config import save_config, get_config_from_file, set_conf
from walt.client.link import ClientToServerLink
from walt.client.node import WalTNode

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

def wait_for_jobs(info):
    while True:
        max_start_time = 0
        waiting_sites = []
        for site in info['sites']:
            job_stat = oarstat(info, site)
            if job_stat['state'] != 'Running':
                waiting_sites.append(site)
                max_start_time = max(max_start_time, job_stat['scheduledStart'])
        if len(waiting_sites) == 0:
            break
        status  = 'waiting.jobs'
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
        log_status_change(self._info, self._status, label)
    def set_default_label(self):
        self.set_label(self._default_label)
    # ignore other calls
    def __getattr__(self, attr):
        return lambda *args: None

def run_deployment_tasks(info):
    wait_for_jobs(info)
    update_vlan_id(info)
    vlan_id = info['vlan']['vlan_id']
    vlan_site = info['vlan']['site']
    update_nodes(info)
    server_site = info['server']['site']
    server_node = info['server']['host']
    server_node_eth1 = '-eth1.'.join(server_node.split('.',maxsplit=1))
    log_status_change(info, 'deploy.vlan', f'Removing default DHCP service on VLAN {vlan_id}', verbose = True)
    run_cmd_on_site(info, vlan_site, f'kavlan -d -i {vlan_id}'.split(), True)
    # deploy server
    log_status_change(info, 'deploy.server', f'Deploying walt server on node {server_node} (expect ~5min)', verbose = True)
    env_file = info['server']['g5k_env_file']
    run_cmd_on_site(info, server_site,
                f'kadeploy3 -m {server_node} -a {env_file}'.split())
    log_status_change(info, 'deploy.server', f'Attaching walt server secondary interface to VLAN {vlan_id}', verbose = True)
    run_cmd_on_site(info, server_site,
                f'kavlan -s -i {vlan_id} -m {server_node_eth1}'.split(), True)
    # configure server
    log_status_change(info, 'deploy.server', 'Configuring walt server', verbose = True)
    send_json_conf_to_server(info)
    run_cmd_on_site(info, server_site,
                f'ssh root@{server_node} /root/walt-server-setup.py /tmp/g5k.json'.split())
    # update server in .waltrc
    log_status_change(info, 'deploy.client_conf', 'Updating $HOME/.waltrc', verbose = True)
    conf = get_config_from_file()
    conf['server'] = server_node
    save_config(conf)
    # boot walt nodes
    log_status_change(info, 'deploy.nodes', f'Attaching walt nodes to VLAN {vlan_id} and rebooting them', verbose = True)
    for site, site_info in info['sites'].items():
        for node in site_info['nodes']:
            run_cmd_on_site(info, site, f'kavlan -s -i {vlan_id} -m {node}'.split(), True)
            run_cmd_on_site(info, site, f'kareboot3 --no-wait -l hard -m {node}'.split())
    # note: waiting for nodes may require user credentials to be available,
    # and they may not be present yet in .waltrc, so set temporary ones.
    conf['username'], conf['password'] = 'anonymous', 'none'
    set_conf(conf)  # temporary conf, not saved in .waltrc
    busy_indicator = LoggerBusyIndicator(info, 'deploy.nodes',
                                         'Waiting for first bootup of nodes')
    with ClientToServerLink(do_checks=False, busy_indicator=busy_indicator) as server:
        WalTNode.wait_for_nodes(server, 'all-nodes')
    log_status_change(info, 'ready', 'Ending WalT platform deployment')
    print('Ready!')

# Note: this helper program is called when the g5k job starts to run,
# at the site where the walt server will be deployed.
# It has to connect back to this site where walt g5k deploy command was run:
# $ oarsub [...] "ssh <this-site> walt-g5k-deploy-helper"
# It should also remain alive to maintain the job alive.
def run():
    info = get_deployment_status()
    log_status_change(info, 'helper-start', 'Running walt-g5k-deploy-helper')
    run_deployment_tasks(info)
    # remain alive
    hours, minutes, seconds = tuple(int(e) for e in info['walltime'].split(':'))
    time.sleep(hours*3600 + minutes*60 + seconds)
