import inspect
from walt.common.devices import switches
from walt.common.devices.switches import *

PROBE_FUNCTIONS = []

def get_device_info_from_mac(mac):
    for probe in PROBE_FUNCTIONS:
        info = probe(mac)
        if info is not None:
            return info
    return {}     # no information found

def register_all_probe_functions():
    all_modules = []
    # add all modules in 'switches' subdir
    for package in (switches,):
        all_modules.extend(module for name, module in \
                    inspect.getmembers(package, inspect.ismodule))
    for module in all_modules:
        PROBE_FUNCTIONS.append(module.probe)

register_all_probe_functions()
