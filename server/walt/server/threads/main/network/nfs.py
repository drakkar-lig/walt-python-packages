import os
from plumbum.cmd import exportfs

from walt.common.tools import do, succeeds
from walt.server.threads.main.network.tools import get_walt_subnet

IMAGE_EXPORT_PATTERN = """\
%(image_mountpoint)s %(walt_subnet)s(fsid=%(fsid)s,ro,sync,no_root_squash,no_subtree_check)\
"""
PERSISTENT_EXPORT_PATTERN = """\
%(persist_mountpoint)s %(walt_subnet)s(rw,sync,no_root_squash,no_subtree_check)\
"""
PERSISTENT_PATH = "/var/lib/walt/nodes/%(node_mac)s/persist"

def get_fsid(image):
    return image.get_top_layer_id()[:32]   # 32 first characters

def generate_exports_file(images, nodes):
    with open('/etc/exports', 'w') as f:
        f.write("# Root filesystem images\n")
        for image in images:
            if image.ready:
                f.write((IMAGE_EXPORT_PATTERN % dict(
                    image_mountpoint=image.mount_path,
                    walt_subnet=get_walt_subnet(),
                    fsid=get_fsid(image)))
                        + "\n")
        f.write("# Persistent node directories\n")
        for node in nodes:
            persist_path = PERSISTENT_PATH % dict(node_mac=node.mac)
            try:
                # ensure persistent directories exists
                os.mkdir(persist_path)
            except OSError:
                # directory already exists
                pass
            f.write((PERSISTENT_EXPORT_PATTERN % dict(
                persist_mountpoint=persist_path,
                walt_subnet=get_walt_subnet()))
                    + "\n")

def update_exported_filesystems(images, nodes):
    generate_exports_file(images, nodes)
    exportfs('-r')
    ensure_nfsd_is_running()

def ensure_nfsd_is_running():
    if not succeeds('pidof nfsd >/dev/null'):
        do('service nfs-kernel-server restart')
