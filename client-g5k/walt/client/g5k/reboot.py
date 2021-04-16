from walt.client.g5k.deploy.status import get_deployment_status
from walt.client.g5k.tools import run_cmd_on_site
from collections import defaultdict

class G5KClientHardRebootHook:
    method_name = "kareboot3"
    @staticmethod
    def reboot(node_macs):
        # this function must return a tuple made of:
        # 1) the list of macs properly rebooted
        # 2) the dict of reboot errors per mac
        site_reboots = defaultdict(list)
        try:
            info = get_deployment_status()
            if info is None:
                raise Exception('Failed to read deployment.json')
            mac_to_info = {}
            for site, site_info in info['sites'].items():
                for node_name, node_info in site_info['nodes'].items():
                    mac = node_info['mac']
                    mac_to_info[mac] = {
                        'site': site,
                        'name': node_name
                    }
            for mac in node_macs:
                node_info = mac_to_info.get(mac)
                if node_info is None:
                    # could not find node's mac adress in deployment file??
                    raise Exception('deployment.json file is invalid')
                site = node_info['site']
                node_info = (node_info['name'], mac)
                site_reboots[site].append(node_info)
        except Exception as e:
            return (), { mac: str(e) for mac in node_macs }
        # info about nodes could be properly retrieved from deployment.json
        # now, let's call kareboot3 on each site
        rebooted_node_macs = []
        reboot_errors = {}
        for site, nodes_info in site_reboots.items():
            site_node_names, site_node_macs = tuple(zip(*nodes_info))
            try:
                run_cmd_on_site(info, site, f'kareboot3 --no-wait -l hard -f -'.split(),
                                input='\n'.join(site_node_names))
                rebooted_node_macs += list(site_node_macs)
            except Exception as e:
                reboot_errors.update({mac: str(e) for mac in site_node_macs})
        return rebooted_node_macs, reboot_errors
