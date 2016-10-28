import inspect
from walt.common.devices import nodes, switches
from walt.common.devices.nodes import *
from walt.common.devices.switches import *

DEVICES = []

def get_node_cls_from_model(model):
    for cls in DEVICES:
        if cls.WALT_TYPE == 'node' and cls.MODEL_NAME == model:
            return cls
    return None     # not found or not a node

def get_device_cls_from_vci_and_mac(vci, mac):
    for cls in DEVICES:
        if cls.is_such_a_device(vci, mac):
            return cls
    return None     # not found

def register_all_devices():
    global DEVICES
    all_modules = []
    # add all modules in 'nodes' and 'switches' subdirs
    for package in (nodes, switches):
        all_modules.extend(module for name, module in \
                    inspect.getmembers(package, inspect.ismodule))
    for module in all_modules:
        DEVICES.extend(module.get_device_classes())

register_all_devices()

