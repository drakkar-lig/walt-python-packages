import logging
import numpy as np
from contextlib import contextmanager
from pathlib import Path
from subprocess import CalledProcessError

from walt.server.exttools import findmnt
from walt.server.tools import serialized

IMAGE_MOUNT_PATH = "/var/lib/walt/images/%s/fs"
SERIALIZED_MOUNTS_LOCK = Path("/var/lib/walt/mount.lock")


def long_image_id(image_id):
    if len(image_id) < 64:
        for p in Path("/var/lib/walt/images").iterdir():
            if p.name.startswith(image_id):
                image_id = p.name
                break
    return image_id


def get_mount_path(image_id):
    return IMAGE_MOUNT_PATH % image_id


def mount_exists(mountpoint):
    try:
        findmnt("--json", mountpoint)
    except CalledProcessError:
        return False
    return True


def get_mount_container_name(image_id):
    return "mount:" + image_id[:12]


def get_mount_image_name(image_id):
    return "localhost/walt/mounts:" + image_id[:12]


def img_print(image_id, msg, **kwargs):
    for line in msg.splitlines():
        line = line.strip()
        if len(line) > 0:
            print(f"image {image_id[:12]}: {line}", **kwargs)


# There seem to be a race condition rarely occurring
# when mounting walt images in parallel.
# When the problem occurs, "buildah mount" seems to
# succeed, "findmnt" works, but "umount" fails with a
# message saying "not mounted" (we need this umount
# when trying to re-mount with NFS options included).
# Additional info:
# - the mount *is* listed by /proc/self/mounts.
# - the mountpoint appears empty
# - running "strace" on the "umount" command shows that
#   statfs() reports an ext2 filesystem instead of overlay,
#   and a simple program confirms this.
# In this situation, there seem to be no way to umount
# the filesystem (if ever it is really mounted??).
#
# It may also be related to the fact we were using
# "umount -lf", when the image was later un-mounted.
# We now use plain "umount" without "-lf".
#
# Still, since there seems to be a kernel issue, we
# implement a file lock to ensure mount (and umount, who knows)
# operations are serialized.


@contextmanager
def serialized_mounts():
    with serialized(SERIALIZED_MOUNTS_LOCK):
        yield


NODE_RW_MOUNT_DTYPE = np.dtype([('node_mac', object),
                                ('image_id', object),
                                ('image_fullname', object)])

def detect_mounts():
    lines = findmnt("-t", "overlay", "-n", "-o", "target").splitlines()
    arr = np.array(lines, str)
    image_mps = arr[np.char.startswith(arr, "/var/lib/walt/images")]
    image_ids = np.char.replace(image_mps, "/var/lib/walt/images/", "")
    image_ids = np.char.replace(image_ids, "/fs", "")
    node_rw_mps = arr[np.char.startswith(arr, "/var/lib/walt/nodes")]
    node_rw_mounts = np.empty(len(node_rw_mps), NODE_RW_MOUNT_DTYPE)
    node_rw_mounts = node_rw_mounts.view(np.recarray)
    if len(node_rw_mounts) > 0:
        words = "\n".join(node_rw_mps).replace("/", "\n").splitlines()
        words_arr = np.array(words, str).reshape((len(node_rw_mps), 11))
        node_rw_mounts.node_mac = words_arr[:, 5]
        node_rw_mounts.image_id = words_arr[:, 7]
        node_rw_mounts.image_fullname = words_arr[:, 8]
        node_rw_mounts.image_fullname += '/'
        node_rw_mounts.image_fullname += words_arr[:, 9]
    return image_ids, node_rw_mounts
