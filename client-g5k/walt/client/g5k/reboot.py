from collections import defaultdict

from walt.client.g5k.deploy.status import get_last_deployment_status
from walt.client.g5k.tools import run_cmd_on_site


def reboot_nodes(info, node_names, retries=3):
    node_names_per_site = defaultdict(set)
    for node_name in node_names:
        site = node_name.split(".")[1]
        node_names_per_site[site].add(node_name)
    rebooted_node_names = []
    for i in range(retries):
        reboot_errors = {}
        for site, site_node_names in node_names_per_site.items():
            if len(site_node_names) == 0:
                continue
            try:
                run_cmd_on_site(
                    info,
                    site,
                    "kareboot3 simple --no-wait -l hard -f -".split(),
                    input="\n".join(site_node_names),
                )
                rebooted_node_names += list(site_node_names)
                site_node_names.clear()
            except Exception as e:
                reboot_errors.update(
                    {node_name: str(e) for node_name in site_node_names}
                )
        if len(reboot_errors) == 0:
            break
    return rebooted_node_names, reboot_errors


class G5KClientHardRebootHook:
    method_name = "kareboot3"

    @staticmethod
    def reboot(node_macs):
        # this function must return a tuple made of:
        # 1) the list of macs properly rebooted
        # 2) the dict of reboot errors per mac
        node_name_to_mac = {}
        mac_to_node_name = {}
        node_names = []
        try:
            info = get_last_deployment_status()
            if info is None:
                raise Exception("Failed to read deployment.json")
            for site, site_info in info["sites"].items():
                for node_name, node_info in site_info["nodes"].items():
                    mac = node_info["mac"]
                    node_name_to_mac[node_name] = mac
                    mac_to_node_name[mac] = node_name
            for mac in node_macs:
                node_name = mac_to_node_name.get(mac)
                if node_name is None:
                    # could not find node's mac adress in deployment file??
                    raise Exception("deployment.json file is invalid")
                node_names.append(node_name)
        except Exception as e:
            return (), {mac: str(e) for mac in node_macs}
        # info about nodes could be properly retrieved from deployment.json
        # now, let's call kareboot3 on each site
        rebooted_node_names, reboot_errors = reboot_nodes(info, node_names)
        # convert node names back to mac
        rebooted_node_macs = [node_name_to_mac[n] for n in rebooted_node_names]
        reboot_errors = {node_name_to_mac[n]: e for n, e in reboot_errors.items()}
        return rebooted_node_macs, reboot_errors
