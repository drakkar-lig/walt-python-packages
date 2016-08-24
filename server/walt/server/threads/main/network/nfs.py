from plumbum.cmd import exportfs
from walt.server import const
from walt.common.tools import do, succeeds

IMAGE_EXPORT_PATTERN = """
%(image_mountpoint)s %(walt_subnet)s(fsid=%(fsid)s,rw,sync,no_root_squash,no_subtree_check)
"""

def get_fsid(image):
    return image.top_layer_id[:32]   # 32 first characters

def generate_exports_file(images):
    with open('/etc/exports', 'w') as f:
        f.write("\n".join([
            IMAGE_EXPORT_PATTERN % dict(
                image_mountpoint=image.mount_path,
                walt_subnet=const.WALT_SUBNET,
                fsid=get_fsid(image)
            ) for image in images ]))

def update_exported_filesystems(images):
    generate_exports_file(images)
    exportfs('-r')
    ensure_nfsd_is_running()

def ensure_nfsd_is_running():
    if not succeeds('pidof nfsd >/dev/null'):
        do('service nfs-kernel-server restart')
