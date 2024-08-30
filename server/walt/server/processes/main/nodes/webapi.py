import json
import numpy as np

from walt.common.netsetup import NetSetup
from walt.server.tools import filter_items_with_query_params


def web_api_list_nodes(devices, settings, webapi_version, query_params):
    assert webapi_version == "v1"
    devices = devices.parse_device_set(None, "all-nodes")
    if devices is None:
        return  # issue already reported
    num_nodes = len(devices)
    configs = settings.get_device_config_data_for_devices(devices)
    # we want the netsetup as a string
    mask_nat_devices = (devices.netsetup == NetSetup.NAT)
    configs.settings[mask_nat_devices] |= {"netsetup": "NAT"}
    mask_lan_devices = (devices.netsetup == NetSetup.LAN)
    configs.settings[mask_lan_devices] |= {"netsetup": "LAN"}
    device_fields = {"name": str, "model": str, "virtual": bool,
                     "image": str, "booted": bool, "ip": str, "mac": str}
    device_field_names = list(device_fields.keys())
    new_dt = [(name, object) for name in (device_field_names + ["config"])]
    nodes = np.empty((num_nodes,), dtype=new_dt).view(np.recarray)
    nodes[device_field_names] = devices[device_field_names]
    nodes.config = configs.settings
    res = filter_items_with_query_params(nodes, device_fields, query_params)
    if not res[0]:
        return res[1]
    nodes = res[1]
    return {
        "code": 200,    # ok
        "num_nodes": len(nodes),
        "nodes": nodes
    }
