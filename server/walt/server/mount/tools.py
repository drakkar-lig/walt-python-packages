import logging
import fcntl
from contextlib import contextmanager
from pathlib import Path
from subprocess import CalledProcessError

from walt.server.exttools import findmnt

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
def serialized(lock_path):
    lock_path.touch()
    with lock_path.open() as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def serialized_mounts():
    with serialized(SERIALIZED_MOUNTS_LOCK):
        yield

