import functools
import os
import sys
import time

from walt.server.exttools import umount, buildah, podman, lsof
from walt.server.mount.tools import get_mount_path, mount_exists, serialized_mounts
from walt.server.mount.tools import img_print as img_print_generic, long_image_id
from walt.server.mount.tools import get_mount_container_name, get_mount_image_name


def image_umount(image_id, mount_path):
    cont_name = get_mount_container_name(image_id)
    if mount_exists(mount_path):
        old_lsof = ""
        while True:
            try:
                umount(mount_path, hide_stderr=True)
                break   # ok, succeeded
            except Exception:
                new_lsof = lsof("-Q", "-Fp", mount_path)
                if new_lsof != old_lsof and new_lsof != "":
                    desc_pids = " ".join(l[1:] for l in new_lsof.splitlines())
                    msg = f"held by process(es) with pid(s) {desc_pids}, will retry."
                    img_print_generic(image_id, msg)
                    old_lsof = new_lsof
                # wait for the last processes to release this
                time.sleep(0.05)
    buildah.umount(cont_name)
    buildah.rm(cont_name)
    image_name = get_mount_image_name(image_id)
    podman.rmi(image_name)


def run():
    if len(sys.argv) != 2:
        sys.exit(f"USAGE: {sys.argv[0]} <image-id>")
    image_id = long_image_id(sys.argv[1])
    img_print = functools.partial(img_print_generic, image_id)
    img_print("un-mounting...")
    mount_path = get_mount_path(image_id)
    with serialized_mounts():
        image_umount(image_id, mount_path)
        os.rmdir(mount_path)
    img_print("un-mounting done")


if __name__ == "__main__":
    run()
