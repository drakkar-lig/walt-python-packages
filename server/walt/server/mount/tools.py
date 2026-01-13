import hashlib
import logging
import operator
import pickle
import numpy as np
from contextlib import contextmanager
from pathlib import Path
from subprocess import CalledProcessError

from walt.server.exttools import findmnt, buildah
from walt.server.tools import serialized, ConcurrentShelve

SERIALIZED_MOUNTS_LOCK = Path("/var/lib/walt/mount.lock")
IMAGE_SIZE_CACHE = ConcurrentShelve(
        "/var/lib/walt/images/image-size-cache")


# Note: the following 4 functions can also work with numpy array arguments

def get_image_mount_path(image_id):
    return "/var/lib/walt/images/" + image_id + "/fs"


def get_node_rw_relative_mount_path(image_id, image_fullname):
    return ("fs_rw/" + image_id + "/" + image_fullname + "/fs")


def get_node_rw_mount_path(node_mac, image_id, image_fullname):
    return ("/var/lib/walt/nodes/" + node_mac + "/" +
            get_node_rw_relative_mount_path(image_id, image_fullname))


_np_path_object = np.vectorize(Path)
_np_read_text = np.vectorize(operator.methodcaller("read_text"))

def get_node_rw_fsid(mount_path):
    if isinstance(mount_path, np.ndarray):
        return _np_read_text(_np_path_object(mount_path + '.fsid'))
    else:
        return Path(str(mount_path) + ".fsid").read_text()


def set_node_rw_fsid(mount_path, fsid):
    Path(str(mount_path) + ".fsid").write_text(fsid)


def long_image_id(image_id):
    if len(image_id) < 64:
        for p in Path("/var/lib/walt/images").iterdir():
            if p.name.startswith(image_id):
                image_id = p.name
                break
    return image_id


def mount_exists(mountpoint):
    try:
        findmnt("--json", mountpoint)
    except CalledProcessError:
        return False
    return True


def get_image_mount_container_name(image_id):
    return "mount:image-" + image_id[:12]


def _node_rw_mount_id(*params):
    mac = params[0].replace(":", "")
    hex_digest = hashlib.sha256(pickle.dumps(params)).hexdigest()[-8:]
    return f"{mac}-{hex_digest}"


def get_node_rw_mount_container_name(node_mac,
                                     image_id, image_fullname):
    mount_id = _node_rw_mount_id(node_mac, image_id, image_fullname)
    return "mount:node-rw-" + mount_id


def get_image_mount_image_name(image_id):
    return "localhost/walt/mount:image-" + image_id[:12]


def get_node_rw_mount_image_name(node_mac,
                                 image_id, image_fullname):
    mount_id = _node_rw_mount_id(node_mac, image_id, image_fullname)
    return "localhost/walt/mount:node-rw-" + mount_id


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
#
# We use this lock to also serialize all calls to buildah command
# because we also have seen a crash case calling "buildah containers"
# while other concurrent walt-image-mount calls were running and
# possibly creating containers.


@contextmanager
def serialized_mounts():
    with serialized(SERIALIZED_MOUNTS_LOCK):
        yield


def save_image_size(image_id, size_kib):
    IMAGE_SIZE_CACHE[image_id] = size_kib


def get_image_size(image_id):
    return IMAGE_SIZE_CACHE[image_id]


def forget_image_sizes():
    IMAGE_SIZE_CACHE.clear()


def image_exists(image):
    try:
        buildah.inspect(image, hide_stderr=True)
        return True
    except CalledProcessError:
        return False


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
        image_mounts.image_id = image_ids
        image_size_cache = dict(IMAGE_SIZE_CACHE)
        image_sizes = np.vectorize(image_size_cache.__getitem__)(image_ids)
        image_mounts.size_kib = image_sizes
    node_rw_mps = mps[np.char.startswith(mps, "/var/lib/walt/nodes")]
    node_rw_mounts = np.empty(len(node_rw_mps), NODE_RW_MOUNT_DTYPE)
    node_rw_mounts = node_rw_mounts.view(np.recarray)
    if len(node_rw_mps) > 0:
        words = "\n".join(node_rw_mps).replace("/", "\n").splitlines()
        words_arr = np.array(words, str).reshape((len(node_rw_mps), 11))
        node_rw_mounts.node_mac = words_arr[:, 5]
        node_rw_mounts.image_id = words_arr[:, 7]
        node_rw_mounts.image_fullname = words_arr[:, 8]
        node_rw_mounts.image_fullname += '/'
        node_rw_mounts.image_fullname += words_arr[:, 9]
    return image_mounts, node_rw_mounts


def discard_mount_images():
    for line in buildah.images().splitlines():
        words = line.split()
        fullname = ":".join(words[:2])
        if fullname.startswith("localhost/walt/mount:image-"):
            buildah.rmi(fullname)
    forget_image_sizes()
