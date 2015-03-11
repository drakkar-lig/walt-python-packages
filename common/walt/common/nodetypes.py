import inspect
from walt.common import devices
from devices import *

NodeTypes = set([])

def register_node_type(node_type_class):
    global NodeTypes
    NodeTypes.add(node_type_class)

def get_node_type_from_mac_address(mac_address):
    for nt in NodeTypes:
        if mac_address.startswith(nt.MAC_PREFIX):
            return nt

def get_node_type_from_name(name):
    for nt in NodeTypes:
        if name == nt.SHORT_NAME:
            return nt
    return None     # not a node

def is_a_node_type_name(name):
    return get_node_type_from_name(name) != None

def register_all_devices():
    for name, module in inspect.getmembers(devices, inspect.ismodule):
        for name, cl in inspect.getmembers(module, inspect.isclass):
            register_node_type(cl)

register_all_devices()

