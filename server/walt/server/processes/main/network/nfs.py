import sys
from pathlib import Path

from walt.server.tools import get_walt_subnet

NODE_SYMLINKS_EXPORT_PATTERN = """\
# Access to node symlinks (necessary for NFSv4).
/var/lib/walt/nodes %(walt_subnet)s(ro,sync,no_root_squash,no_subtree_check)
"""
IMAGE_EXPORT_PATTERN = """\
%(image_mountpoint)s %(walt_subnet)s\
(fsid=%(fsid)s,ro,sync,no_root_squash,no_subtree_check)
"""
PERSISTENT_EXPORT_PATTERN = """\
%(persist_mountpoint)s %(walt_subnet)s(rw,sync,no_root_squash,no_subtree_check)
"""
WALT_IMAGE_EXPORTS_PATH = Path("/etc/exports.d/walt.exports")
WALT_PERSIST_EXPORTS_PATH = Path("/etc/exports.d/walt-persist.exports")


def generate_image_exports_file_content(root_paths, subnet):
    """Regenerate the NFS image exports file according to the current configuration."""
    content = "# WALT NFS image exports: this file is automatically generated.\n"
    if len(root_paths) == 0:
        return content
    content += NODE_SYMLINKS_EXPORT_PATTERN % dict(walt_subnet=subnet)
    content += "# Root filesystem images\n"
    for root_path, fsid in sorted(root_paths):
        content += IMAGE_EXPORT_PATTERN % dict(
            image_mountpoint=root_path, walt_subnet=subnet, fsid=fsid
        )
    return content


def generate_persist_exports_file_content(persist_paths):
    """Regenerate the NFS persist exports according to the current configuration."""
    subnet = get_walt_subnet()
    content = "# WALT NFS persist exports: this file is automatically generated.\n"
    if len(persist_paths) == 0:
        return content
    content += "# Persistent node directories\n"
    for persist_path in sorted(persist_paths):
        content += PERSISTENT_EXPORT_PATTERN % dict(
            persist_mountpoint=persist_path, walt_subnet=subnet
        )
    return content


class NFSExporter(object):
    def __init__(self, ev_loop):
        self._ev_loop = ev_loop

    def _get_prev_content_or_init(self, path):
        if not path.parent.exists():
            path.parent.mkdir()
        if path.exists():
            return path.read_text()
        else:
            return ""

    def _wf_run_exportfs(self, wf, **env):
        self._ev_loop.do("exportfs -r -f", wf.next)

    def _wf_after_exportfs(self, wf, retcode, **env):
        if retcode != 0:
            print("Warning: exportfs failed!", file=sys.stderr)
        wf.next()

    def wf_update_image_exports(self, wf, root_paths, subnet, **env):
        prev_content = self._get_prev_content_or_init(WALT_IMAGE_EXPORTS_PATH)
        content = generate_image_exports_file_content(root_paths, subnet)
        if content != prev_content:
            WALT_IMAGE_EXPORTS_PATH.write_text(content)
            wf.insert_steps([self._wf_run_exportfs, self._wf_after_exportfs])
        wf.next()

    def wf_update_persist_exports(self, wf, persist_paths, nfsd_restart=True, **env):
        prev_content = self._get_prev_content_or_init(WALT_PERSIST_EXPORTS_PATH)
        content = generate_persist_exports_file_content(persist_paths)
        if content != prev_content:
            WALT_PERSIST_EXPORTS_PATH.write_text(content)
            wf.insert_steps([self._wf_run_exportfs, self._wf_after_exportfs])
        wf.next()
