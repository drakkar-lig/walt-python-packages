import functools
import json
import os
import random
import shutil
import sys

from pathlib import Path
from subprocess import CalledProcessError

from walt.common.tools import failsafe_makedirs
from walt.server.exttools import findmnt, umount, mount, buildah
from walt.server.mount.tools import (
        get_image_mount_container_name,
        get_image_mount_image_name,
        get_image_mount_path,
        get_image_size,
        get_node_rw_mount_container_name,
        get_node_rw_mount_image_name,
        get_node_rw_mount_path,
        image_exists,
        img_print,
        mount_exists,
        node_rw_print,
        long_image_id,
        save_image_size,
        serialized_mounts,
        set_node_rw_fsid,
)
from walt.server.mount.setup import setup

IMAGE_LAYERS_DIR = "/var/lib/containers/storage/overlay"
USAGE = f"""\
USAGE:
{sys.argv[0]} --image <img-id> <img-size-kib>
or
{sys.argv[0]} --node-rw <node-mac> <img-id> <img-fullname>
"""


# 'buildah mount' does not mount the overlay filesystem with appropriate
# options to allow nfs export. let's fix this.
def remount_with_nfs_export_option(mountpoint):
    # retrieve mount info
    json_info = findmnt("--json", mountpoint)
    mount_info = json.loads(json_info)["filesystems"][0]
    source = mount_info["source"]
    fstype = mount_info["fstype"]
    options = mount_info["options"].split(",")
    # update options
    # note: if not already done by buildah, we make options text more
    # compact by using paths relative to IMAGE_LAYERS_DIR
    new_options = ["rw", "relatime", "index=on", "nfs_export=on"] + [
        opt.replace(f"{IMAGE_LAYERS_DIR}/", "")
        for opt in options
        if opt.startswith("lowerdir")
        or opt.startswith("upperdir")
        or opt.startswith("workdir")
    ]
    # umount
    with serialized_mounts():
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
    # when having many layers, buildah / podman specify them relative to
    # the following directory
    os.chdir(IMAGE_LAYERS_DIR)
    # re-mount
    with serialized_mounts():
        mount("-t", fstype, "-o", ",".join(new_options), source, mountpoint)


def list_buildah_containers():
    with serialized_mounts():
        return buildah.containers(
                "--format", "{{.ContainerName}}").splitlines()


def failsafe_buildah_from(log_print, image, cont_name):
    if cont_name in list_buildah_containers():
        log_print(
            "Note: walt server was probably not stopped properly "
            "and container still exists. Going on."
        )
    else:
        with serialized_mounts():
            buildah("from", "--pull-never", "--name", cont_name, image)


def image_mount(log_print, image_id, image_size_kib):
    mount_path = get_image_mount_path(image_id)
    # if server daemon was killed and restarted, the mount may
    # still be there
    if mount_exists(mount_path):
        return False  # nothing to do
    cont_name = get_image_mount_container_name(image_id)
    image_name = get_image_mount_image_name(image_id)
    if not image_exists(image_name):
        # create a buildah container
        save_image_size(image_id, image_size_kib)
        failsafe_buildah_from(log_print, image_id, cont_name)
        # mount the container content in a directory
        with serialized_mounts():
            buildah_mount_path = buildah.mount(cont_name)
        # call setup code
        setup(image_id, buildah_mount_path, image_size_kib, log_print)
        # commit the setup changes
        with serialized_mounts():
            buildah.commit("--format", "docker", cont_name, image_name,
                       hide_stderr=True)
            buildah.umount(cont_name)
            buildah.rm(cont_name)
    # re-start the buildah container from this image with setup changes
    failsafe_buildah_from(log_print, image_name, cont_name)
    with serialized_mounts():
        buildah_mount_path = buildah.mount(cont_name)
    # fix the mount options and bind to mount_path
    remount_with_nfs_export_option(buildah_mount_path)
    failsafe_makedirs(mount_path)
    with serialized_mounts():
        mount("--bind", buildah_mount_path, mount_path)


def node_rw_mount(log_print, node_mac, image_id, image_fullname):
    mount_path = get_node_rw_mount_path(
            node_mac, image_id, image_fullname)
    failsafe_makedirs(mount_path)
    # if server daemon was killed and restarted, the mount may
    # still be there
    if mount_exists(mount_path):
        return False  # nothing to do
    cont_name = get_node_rw_mount_container_name(
            node_mac, image_id, image_fullname)
    image_name = get_node_rw_mount_image_name(
            node_mac, image_id, image_fullname)
    # Containers of node-rw mounts (aka nodes with
    # boot-mode=network-persistent) are not removed when the server
    # restarts, because we don't want to lose the data they hold,
    # so let's check if this container already exists or if it's new.
    new_container = False
    if not cont_name in list_buildah_containers():
        # Save the image linked to the image mount as a new name
        # specific to this node-rw mount, and we'll start the container
        # from it. This allows to eventually umount the source image
        # without having to remove this container.
        src_image_name = get_image_mount_image_name(image_id)
        with serialized_mounts():
            buildah.tag(src_image_name, image_name)
            buildah("from", "--pull-never", "--name", cont_name, image_name)
        # generate a random fsid for this new container
        set_node_rw_fsid(mount_path, random.randbytes(16).hex())
        # we've just created the container
        new_container = True
    # mount the container content in a directory
    with serialized_mounts():
        buildah_mount_path = buildah.mount(cont_name)
    # if the container is old, restart the setup() procedure
    # to ensure any change in server code having occurred since this
    # existing container was created is taken into account.
    if not new_container:
        image_size_kib = get_image_size(image_id)
        setup(image_id, buildah_mount_path, image_size_kib, log_print,
              process_image_spec=False)
    # fix the mount options and bind to mount_path
    remount_with_nfs_export_option(buildah_mount_path)
    with serialized_mounts():
        mount("--bind", buildah_mount_path, mount_path)


def run():
    if len(sys.argv) == 4 and sys.argv[1] == "--image":
        image_id = long_image_id(sys.argv[2])
        image_size_kib = int(sys.argv[3])
        log_print = functools.partial(img_print, image_id)
        log_print("mounting...")
        image_mount(log_print, image_id, image_size_kib)
        log_print("mounting done")
    elif len(sys.argv) == 5 and sys.argv[1] == "--node-rw":
        node_mac = sys.argv[2]
        image_id = long_image_id(sys.argv[3])
        image_fullname = sys.argv[4]
        log_print = functools.partial(node_rw_print, node_mac)
        log_print("mounting...")
        node_rw_mount(log_print, node_mac, image_id, image_fullname)
        log_print("mounting done")
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    run()
