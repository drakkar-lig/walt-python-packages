from pathlib import Path
from walt.common.tools import do, succeeds

NODE_SYMLINKS_EXPORT_PATTERN = """\
# Access to node symlinks (necessary for NFSv4).
/var/lib/walt/nodes %(walt_subnet)s(ro,sync,no_root_squash,no_subtree_check)
"""
IMAGE_EXPORT_PATTERN = """\
%(image_mountpoint)s %(walt_subnet)s(fsid=%(fsid)s,ro,sync,no_root_squash,no_subtree_check)
"""
PERSISTENT_EXPORT_PATTERN = """\
%(persist_mountpoint)s %(walt_subnet)s(rw,sync,no_root_squash,no_subtree_check)
"""
WALT_EXPORTS_PATH = Path("/etc/exports.d/walt.exports")

def generate_exports_file(root_paths, persist_paths, subnet):
    """Regenerate the NFS exports file according to the current configuration."""
    if not WALT_EXPORTS_PATH.parent.exists():
        WALT_EXPORTS_PATH.parent.mkdir()
    with WALT_EXPORTS_PATH.open('w') as f:
        f.write("# WALT NFS exports: this file is automatically generated.\n")
        if len(root_paths) == 0:
            return
        f.write(NODE_SYMLINKS_EXPORT_PATTERN % dict(walt_subnet=subnet))
        f.write("# Root filesystem images\n")
        for root_path, fsid in root_paths:
            f.write(IMAGE_EXPORT_PATTERN % dict(
                    image_mountpoint=root_path,
                    walt_subnet=subnet,
                    fsid=fsid))
        f.write("# Persistent node directories\n")
        for persist_path in persist_paths:
            f.write(PERSISTENT_EXPORT_PATTERN % dict(
                    persist_mountpoint=persist_path,
                    walt_subnet=subnet))

def update_exports(root_paths, persist_paths, subnet):
    generate_exports_file(root_paths, persist_paths, subnet)
    # note: use restart and not reload because otherwise with NFSv4
    # it takes times before NFS clients no longer allowed are disconnected,
    # and this delays unmounting of images.
    do('systemctl restart nfs-kernel-server')
    ensure_nfsd_is_running()

def ensure_nfsd_is_running():
    if not succeeds('pidof nfsd >/dev/null'):
        do('systemctl restart nfs-kernel-server')
