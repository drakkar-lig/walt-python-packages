import functools
import json
import os
import shutil
import sys

from pathlib import Path
from subprocess import CalledProcessError

from walt.common.tools import failsafe_makedirs
from walt.server.exttools import findmnt, umount, mount, buildah, podman
from walt.server.mount.tools import get_image_mount_path, mount_exists, serialized_mounts
from walt.server.mount.tools import img_print, node_rw_print, long_image_id
from walt.server.mount.tools import get_mount_container_name, get_mount_image_name
from walt.server.mount.tools import save_image_size
from walt.server.mount.setup import setup

IMAGE_LAYERS_DIR = "/var/lib/containers/storage/overlay"
USAGE = f"""\
USAGE:
{sys.argv[0]} --image <img-id> <img-size-kib>
or
{sys.argv[0]} --node-rw <node-mac> <img-id> <img-size-kib> <img-fullname>
"""

def get_mount_info(mountpoint):
    json_info = findmnt("--json", mountpoint)
    mount_info = json.loads(json_info)["filesystems"][0]
    mount_info["options"] = mount_info["options"].split(",")
    return mount_info


def do_mount(fstype, options, source, mountpoint):
    mount("-t", fstype, "-o", ",".join(options), source, mountpoint)


# 'buildah mount' does not mount the overlay filesystem with
# appropriate options to allow nfs export. let's fix this.
def remount_with_nfs_export_option(mountpoint):
    # retrieve mount info
    mount_info = get_mount_info(mountpoint)
    source = mount_info["source"]
    fstype = mount_info["fstype"]
    options = mount_info["options"]
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
    do_mount(fstype, new_options, source, mountpoint)


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


def node_rw_mount(node_mac, image_id, image_fullname):
    # prepare overlay directories, clearing work_dir if not empty
    # after a previous crash
    overlay_dir = get_node_rw_overlay_path(
            node_mac, image_id, image_fullname)
    node_rw_mountpoint = overlay_dir / "merged"
    diff_dir = overlay_dir / "diff"
    work_dir = overlay_dir / "work"
    for work_dir.exists():
        shutil.rmtree(work_dir)
    for d in (mount_dir, diff_dir, work_dir):
        d.mkdir(parents=True, exist_ok=True)
    # retrieve image mount info
    image_mountpoint = get_image_mount_path(image_id)
    mount_info = get_mount_info(image_mountpoint)
    source = mount_info["source"]
    fstype = mount_info["fstype"]
    options = mount_info["options"]
    # analyse image mount options
    opt_lowerdir, opt_upperdir, opt_workdir = None, None, None
    other_options = []
    for opt in options:
        if opt.startswith("lowerdir"):
            opt_lowerdir = opt
        elif opt.startswith("upperdir"):
            opt_upperdir = opt
        elif opt.startswith("workdir"):
            pass    # we don't need this
        else:
            other_options.append(opt)
    # move upperdir of image mount to the end of lowerdirs
    opt_lowerdir += ":" + opt_upperdir.split('=')[1]
    # we added one more lowerdir layer, so let's make sure we
    # use the condensed form, otherwise we could exceed the max
    # mount option length
    opt_lowerdir = opt_lowerdir.replace(f"{IMAGE_LAYERS_DIR}/", "")
    # set the new upperdir and workdir
    opt_upperdir = "upperdir=" + str(diff_dir)
    opt_workdir = "workdir=" + str(work_dir)
    # perform the mount
    new_options = other_options + [opt_lowerdir, opt_upperdir, opt_workdir]
    os.chdir(IMAGE_LAYERS_DIR)
    do_mount(fstype, new_options, source, node_rw_mountpoint)


def run():
    if len(sys.argv) == 4 and sys.argv[1] == "--image":
        image_id = long_image_id(sys.argv[2])
        image_size_kib = int(sys.argv[3])
        log_print = functools.partial(img_print, image_id)
        log_print("mounting...")
        mount_path = get_image_mount_path(image_id)
        with serialized_mounts():
            failsafe_makedirs(mount_path)
            image_mount(image_id, mount_path)
            save_image_size(image_id, image_size_kib)
        setup(image_id, mount_path, image_size_kib, log_print)
        log_print("mounting done")
    elif len(sys.argv) == 5 and sys.argv[1] == "--node-rw":
        node_mac = sys.argv[2]
        image_id = long_image_id(sys.argv[3])
        image_fullname = sys.argv[4]
        log_print = functools.partial(node_rw_print, node_mac)
        log_print("mounting...")
        with serialized_mounts():
            node_rw_mount(node_mac, image_id, image_fullname)
        log_print("mounting done")
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    run()
