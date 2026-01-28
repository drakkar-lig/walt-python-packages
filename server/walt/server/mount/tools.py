import logging
import numpy as np
from contextlib import contextmanager
from pathlib import Path
from subprocess import CalledProcessError

from walt.server.exttools import findmnt
from walt.server.tools import serialized

IMAGE_MOUNT_PATH = "/var/lib/walt/images/%s/fs"
NODE_RW_OVERLAY_PATH = "/var/lib/walt/nodes/%s/fs_rw/%s/%s"
SERIALIZED_MOUNTS_LOCK = Path("/var/lib/walt/mount.lock")
IMAGE_SIZE_CACHE = Path("/var/lib/walt/images/image-size-cache.pickle")


def long_image_id(image_id):
    if len(image_id) < 64:
        for p in Path("/var/lib/walt/images").iterdir():
            if p.name.startswith(image_id):
                image_id = p.name
                break
    return image_id


def get_image_mount_path(image_id):
    return IMAGE_MOUNT_PATH % image_id


def get_node_rw_overlay_path(node_mac, image_id, image_fullname):
    return NODE_RW_OVERLAY_PATH % (node_mac, image_id, image_fullname)


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


def node_rw_print(node_mac, msg, **kwargs):
    for line in msg.splitlines():
        line = line.strip()
        if len(line) > 0:
            print(f"node-rw {node_mac}: {line}", **kwargs)


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


# Those two following functions should also be called in
# the serialized_mounts() context.

def save_image_size(image_id, size_kib):
    if IMAGE_SIZE_CACHE.exists():
        size_cache = pickle.loads(IMAGE_SIZE_CACHE.read_bytes())
    else:
        IMAGE_SIZE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        size_cache = {}
    size_cache[image_id] = size_kib
    IMAGE_SIZE_CACHE.write_bytes(pickle.dumps(size_cache))


def forget_image_size(image_id):
    size_cache = pickle.loads(IMAGE_SIZE_CACHE.read_bytes())
    del size_cache[image_id]
    IMAGE_SIZE_CACHE.write_bytes(pickle.dumps(size_cache))


IMAGE_MOUNT_DTYPE = np.dtype([('image_id', object),
                              ('size_kib', object)])
NODE_RW_MOUNT_DTYPE = np.dtype([('node_mac', object),
                                ('image_id', object),
                                ('image_fullname', object)])

def detect_mounts():
    lines = findmnt("-t", "overlay", "-n", "-o", "target").splitlines()
    mps = np.array(lines, str)
    image_mps = mps[np.char.startswith(mps, "/var/lib/walt/images")]
    image_mounts = np.empty(len(image_mps), IMAGE_MOUNT_DTYPE)
    image_mounts = image_mounts.view(np.recarray)
    if len(image_mps) > 0:
        image_ids = np.char.replace(image_mps, "/var/lib/walt/images/", "")
        image_ids = np.char.replace(image_ids, "/fs", "")
        image_mounts.image_ids = image_ids
        size_cache = pickle.loads(IMAGE_SIZE_CACHE.read_bytes())
        image_sizes = np.vectorize(size_cache.__getitem__)(image_ids)
        image_mounts.size_kib = image_sizes
    node_rw_mps = mps[np.char.startswith(mps, "/var/lib/walt/nodes")]
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
    return image_mounts, node_rw_mounts
