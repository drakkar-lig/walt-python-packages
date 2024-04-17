import functools
import json
import os
import shutil
import sys

from pathlib import Path
from subprocess import CalledProcessError

from walt.common.tools import failsafe_makedirs
from walt.server.exttools import findmnt, umount, mount, buildah, podman
from walt.server.mount.tools import get_mount_path, mount_exists, serialized_mounts
from walt.server.mount.tools import img_print as img_print_generic, long_image_id
from walt.server.mount.tools import get_mount_container_name, get_mount_image_name
from walt.server.mount.setup import setup

IMAGE_LAYERS_DIR = "/var/lib/containers/storage/overlay"


# 'buildah mount' does not mount the overlay filesystem with appropriate options to
# allow nfs export. let's fix this.
def remount_with_nfs_export_option(mountpoint):
    # retrieve mount info
    json_info = findmnt("--json", mountpoint)
    mount_info = json.loads(json_info)["filesystems"][0]
    source = mount_info["source"]
    fstype = mount_info["fstype"]
    options = mount_info["options"].split(",")
    # update options
    new_options = ["rw", "relatime", "index=on", "nfs_export=on"] + [
        opt
        for opt in options
        if opt.startswith("lowerdir")
        or opt.startswith("upperdir")
        or opt.startswith("workdir")
    ]
    # umount
    umount(mountpoint)
    # overlay has a check in place to prevent mounting the same file system
    # twice if volatile was already specified.
    for opt in options:
        if opt.startswith("workdir"):
            workdir = Path(opt[len("workdir=") :])
            incompat_volatile = workdir / "work" / "incompat" / "volatile"
            if incompat_volatile.exists():
                shutil.rmtree(incompat_volatile)
            break
    # when having many layers, podman specifies them relative to the
    # following directory
    os.chdir(IMAGE_LAYERS_DIR)
    # re-mount
    mount("-t", fstype, "-o", ",".join(new_options), source, mountpoint)


def image_mount(image_id, mount_path):
    # if server daemon was killed and restarted, the mount may still be there
    if mount_exists(mount_path):
        return False  # nothing to do
    # in some cases the code may remove the last tag of an image whilst it is
    # still mounted, waiting for grace time expiry. this fails.
    # in order to avoid this we attach a new tag to all images we mount.
    image_name = get_mount_image_name(image_id)
    try:
        podman("tag", str(image_id), image_name)
    except CalledProcessError:
        pass  # walt server was probably not stopped properly, tag is still there
    # create a buildah container and use the buildah mount command
    cont_name = get_mount_container_name(image_id)
    try:
        buildah("from", "--pull-never", "--name", cont_name, image_id)
    except CalledProcessError:
        print(
            "Note: walt server was probably not stopped properly and container"
            " still exists. Going on."
        )
    dir_name = buildah.mount(cont_name)
    remount_with_nfs_export_option(dir_name)
    mount("--bind", dir_name, mount_path)
    return True


def run():
    if len(sys.argv) != 3:
        sys.exit(f"USAGE: {sys.argv[0]} <image-id> <image-size-kib>")
    image_id = long_image_id(sys.argv[1])
    image_size_kib = int(sys.argv[2])
    img_print = functools.partial(img_print_generic, image_id)
    img_print("mounting...")
    mount_path = get_mount_path(image_id)
    with serialized_mounts():
        failsafe_makedirs(mount_path)
        image_mount(image_id, mount_path)
    setup(image_id, mount_path, image_size_kib, img_print)
    img_print("mounting done")


if __name__ == "__main__":
    run()
