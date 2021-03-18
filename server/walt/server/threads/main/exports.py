from walt.common.tools import failsafe_makedirs
from walt.server.threads.main.network.tools import get_walt_subnet
from walt.server.threads.main.network import nfs, nbfs

PERSISTENT_PATH = "/var/lib/walt/nodes/%(node_mac)s/persist"

def get_fsid(image_id):
    return image_id[:32]   # 32 first characters

def get_exports_info(images_info, nodes):
    # compute the root filesystems of given images
    root_paths = { mount_path: get_fsid(image_id) \
                   for (image_id, mount_path) in images_info }
    # compute persistent node directories
    persist_paths = []
    for node in nodes:
        persist_path = PERSISTENT_PATH % dict(node_mac=node.mac)
        # ensure directory exists
        failsafe_makedirs(persist_path)
        persist_paths.append(persist_path)
    return root_paths, persist_paths

def update_exported_filesystems(images_info, nodes):
    subnet = get_walt_subnet()
    root_paths, persist_paths = get_exports_info(images_info, nodes)
    nfs.update_exports(root_paths.items(), persist_paths, subnet)
    nbfs.update_exports(root_paths.keys(), subnet)
