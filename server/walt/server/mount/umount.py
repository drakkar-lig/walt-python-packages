import functools
import os
import sys
import time

from walt.server.exttools import umount, buildah, podman, lsof
from walt.server.mount.tools import get_image_mount_path, mount_exists, serialized_mounts
from walt.server.mount.tools import img_print, node_rw_print, long_image_id
from walt.server.mount.tools import get_mount_container_name, get_mount_image_name
from walt.server.mount.tools import forget_image_size


def do_umount(mount_path, log_print):
    if mount_exists(mount_path):
        old_lsof = ""
        while True:
            try:
                umount(mount_path, hide_stderr=True)
                break   # ok, succeeded
            except Exception:
                new_lsof = lsof("-Q", "-Fp", mount_path)
                if new_lsof != old_lsof and new_lsof != "":
                    desc_pids = " ".join(
                            l[1:] for l in new_lsof.splitlines())
                    log_print("held by process(es) with pid(s) " +
                              f"{desc_pids}, will retry.")
                    old_lsof = new_lsof
                # wait for the last processes to release this
                time.sleep(0.05)


def image_umount(image_id, mount_path, log_print):
    cont_name = get_mount_container_name(image_id)
    do_umount(mount_path, log_print)
    buildah.umount(cont_name)
    buildah.rm(cont_name)
    image_name = get_mount_image_name(image_id)
    podman.rmi(image_name)


def node_rw_umount(node_mac, image_id, image_fullname, log_print):
    overlay_dir = get_node_rw_overlay_path(
            node_mac, image_id, image_fullname)
    node_rw_mountpoint = overlay_dir / "merged"
    do_umount(node_rw_mountpoint, log_print)


def run():
    if len(sys.argv) == 3 and sys.argv[1] == "--image":
        image_id = long_image_id(sys.argv[2])
        log_print = functools.partial(img_print, image_id)
        log_print("un-mounting...")
        mount_path = get_image_mount_path(image_id)
        with serialized_mounts():
            image_umount(image_id, mount_path, log_print)
            os.rmdir(mount_path)
            forget_image_size(image_id)
        log_print("un-mounting done")
    elif len(sys.argv) == 5 and sys.argv[1] == "--node-rw":
        node_mac = sys.argv[2]
        image_id = long_image_id(sys.argv[3])
        image_fullname = sys.argv[4]
        log_print = functools.partial(node_rw_print, node_mac)
        log_print("un-mounting...")
        with serialized_mounts():
            node_rw_umount(node_mac, image_id, image_fullname, log_print)
        log_print("un-mounting done")
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    run()
