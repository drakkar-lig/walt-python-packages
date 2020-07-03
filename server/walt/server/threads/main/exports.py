from walt.common.tools import failsafe_makedirs
from walt.server.threads.main.network.tools import get_walt_subnet
from walt.server.threads.main.network import nfs, netbootfs

PERSISTENT_PATH = "/var/lib/walt/nodes/%(node_mac)s/persist"

def get_fsid(image):
    return image.image_id[:32]   # 32 first characters

def get_exports_info(images, nodes):
    # compute the set of root filesystem images
    # note: we may have duplicate images refering to the same
    # mountpoint, we should export them only once.
    root_paths = {}
    for image in images:
        if image.ready and image.mounted and image.mount_path not in root_paths:
            root_paths[image.mount_path] = get_fsid(image)
    # compute persistent node directories
    persist_paths = []
    for node in nodes:
        persist_path = PERSISTENT_PATH % dict(node_mac=node.mac)
        # ensure directory exists
        failsafe_makedirs(persist_path)
        persist_paths.append(persist_path)
    return root_paths, persist_paths

def update_exported_filesystems(images, nodes):
    subnet = get_walt_subnet()
    root_paths, persist_paths = get_exports_info(images, nodes)
    nfs.update_exports(root_paths.items(), persist_paths, subnet)
    netbootfs.update_exports(root_paths.keys(), subnet)
