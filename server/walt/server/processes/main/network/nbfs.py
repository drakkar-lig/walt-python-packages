import socket
from pathlib import Path

from walt.common.unix import bind_to_random_sockname

NBFSD_CTL_SOCK_PATH = Path("/run/nbfsd/ctl.sock")
NBFS_EXPORTS_PATH = Path("/etc/nbfsd/exports.d/walt.exports")

IMAGE_EXPORT_PATTERN = """\
%(image_mountpoint)s %(walt_subnet)s(fsid=%(fsid)s)
"""


def generate_exports_file_content(root_paths, subnet):
    lines = [
        "# WALT nbfsd exports: this file is automatically generated.\n",
        "# Root filesystem images\n",
    ]
    for root_path, fsid in sorted(root_paths):
        lines.append(
            IMAGE_EXPORT_PATTERN
            % dict(image_mountpoint=root_path, walt_subnet=subnet, fsid=fsid)
        )
    return "".join(lines)


nbfsd_ctl_sock = None


def update_image_exports(root_paths, subnet):
    global nbfsd_ctl_sock
    NBFS_EXPORTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if NBFS_EXPORTS_PATH.exists():
        prev_content = NBFS_EXPORTS_PATH.read_text()
    else:
        prev_content = ""
    content = generate_exports_file_content(root_paths, subnet)
    if content == prev_content:  # no changes
        return
    NBFS_EXPORTS_PATH.write_text(content)
    # NBFSD_CTL_SOCK should exist if nbfsd is installed and running
    if NBFSD_CTL_SOCK_PATH.exists():
        if nbfsd_ctl_sock is None:
            nbfsd_ctl_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            bind_to_random_sockname(nbfsd_ctl_sock)
            nbfsd_ctl_sock.connect(str(NBFSD_CTL_SOCK_PATH))
        try:
            nbfsd_ctl_sock.send(b"RELOAD_CONF")
            resp = nbfsd_ctl_sock.recv(1024)
            if resp != b"OK":
                print("Error: RELOAD_CONF request to nbfsd failed.",
                      file=sys.stderr)
        except Exception as e:
            print(f"Error: sending RELOAD_CONF request to nbfsd failed: {e}")
