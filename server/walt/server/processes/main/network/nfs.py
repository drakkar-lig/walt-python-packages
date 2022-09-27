from pathlib import Path

from walt.common.tools import do, succeeds
from walt.server import conf

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

def generate_exports_file_content(root_paths, persist_paths, subnet):
    """Regenerate the NFS exports file according to the current configuration."""
    content = "# WALT NFS exports: this file is automatically generated.\n"
    if len(root_paths) == 0:
        return content
    content += NODE_SYMLINKS_EXPORT_PATTERN % dict(walt_subnet=subnet)
    content += "# Root filesystem images\n"
    for root_path, fsid in sorted(root_paths):
        content += IMAGE_EXPORT_PATTERN % dict(
                    image_mountpoint=root_path,
                    walt_subnet=subnet,
                    fsid=fsid)
    content += "# Persistent node directories\n"
    for persist_path in sorted(persist_paths):
        content += PERSISTENT_EXPORT_PATTERN % dict(
                    persist_mountpoint=persist_path,
                    walt_subnet=subnet)
    return content

def update_exports(root_paths, persist_paths, subnet):
    if not WALT_EXPORTS_PATH.parent.exists():
        WALT_EXPORTS_PATH.parent.mkdir()
    if WALT_EXPORTS_PATH.exists():
        prev_content = WALT_EXPORTS_PATH.read_text()
    else:
        prev_content = ""
    content = generate_exports_file_content(root_paths, persist_paths, subnet)
    if content == prev_content:     # no changes
        return
    WALT_EXPORTS_PATH.write_text(content)
    # note: use restart and not reload because otherwise with NFSv4
    # it takes times before NFS clients no longer allowed are disconnected,
    # and this delays unmounting of images.
    service_name = conf['services']['nfsd']['service-name']
    do('systemctl restart "%s"' % service_name)

def ensure_nfsd_is_running():
    if not succeeds('pidof nfsd'):
        service_name = conf['services']['nfsd']['service-name']
        do('systemctl restart "%s"' % service_name)
