import functools
import os
import sys
import time
from pathlib import Path

from walt.server.exttools import umount, buildah, lsof
from walt.server.mount.tools import (
        get_image_mount_path,
        get_node_rw_mount_path,
        mount_exists,
        serialized_mounts,
        img_print,
        node_rw_print,
        long_image_id,
        get_image_mount_container_name,
        get_image_mount_image_name,
        get_node_rw_mount_container_name,
        get_node_rw_mount_image_name,
)


# Returns a decription of the processes preventing the umount.
# Notes:
# - `lsof -Q -Fp` may return spurious pids corresponding to processes
#   using bind-mounts of the mount_path. Those processes do *not* actually
#   prevent the umount. That's why we run a dedicated `lsof -p <pid>` for
#   each of them and verify the mount path is really part of their list of
#   open files.
# - The NFS server may also prevent the umount if it was not properly
#   updated and still exports this image. Since it's implemented in
#   kernel space, it will not be listed by `lsof`. Other kernel objects
#   (e.g., sub-mounts, debugable with 'findmnt --tree') may block the
#   umount without being listed too.
def detect_processes_preventing_umount(mount_path):
    lsof_res1 = lsof("-Q", "-Fp", mount_path)
    if lsof_res1 == "":
        return ""
    processes_desc = []
    for line in lsof_res1.splitlines():
        pid = line[1:]
        lsof_res2 = lsof("-Q", "-Fnc", "-p", pid)
        found = False
        desc = f"pid {pid}"
        for line in lsof_res2.splitlines():
            if line == "n" + mount_path:
                found = True
            elif line.startswith("c"):
                desc = f"- pid {pid} ({line[1:]})"
        if found:
            processes_desc.append(desc)
    return "\n".join(processes_desc)


def do_umount(mount_path, log_print):
    if mount_exists(mount_path):
        old_desc = ""
        while True:
            try:
                with serialized_mounts():
                    umount(mount_path, hide_stderr=True)
                    break   # ok, succeeded
            except Exception:
                new_desc = detect_processes_preventing_umount(mount_path)
                if new_desc != old_desc and new_desc != "":
                    log_print("held by following process(es), will retry.")
                    log_print(new_desc)
                    old_desc = new_desc
                # wait for the last processes to release this
                time.sleep(0.05)


def image_umount(log_print, image_id):
    mount_path = get_image_mount_path(image_id)
    cont_name = get_image_mount_container_name(image_id)
    do_umount(mount_path, log_print)
    with serialized_mounts():
        buildah.umount(cont_name)
        buildah.rm(cont_name)
    os.rmdir(mount_path)


def node_rw_umount(log_print, preserve_container,
                   node_mac, image_id, image_fullname):
    mount_path = get_node_rw_mount_path(
            node_mac, image_id, image_fullname)
    image_name = get_node_rw_mount_image_name(
            node_mac, image_id, image_fullname)
    cont_name = get_node_rw_mount_container_name(
            node_mac, image_id, image_fullname)
    do_umount(mount_path, log_print)
    with serialized_mounts():
        buildah.umount(cont_name)
    # we discard the buildah container holding the changes only
    # in the case of an explicit change requested by the user
    # (e.g., booting another image on this node, or changing its boot-mode),
    # not when the server daemon is stopping.
    if not preserve_container:
        with serialized_mounts():
            buildah.rm(cont_name)
            buildah.rmi(image_name)


def run():
    if len(sys.argv) == 3 and sys.argv[1] == "--image":
        image_id = long_image_id(sys.argv[2])
        log_print = functools.partial(img_print, image_id)
        log_print("un-mounting...")
        image_umount(log_print, image_id)
        log_print("un-mounting done")
    elif len(sys.argv) >= 5 and sys.argv[1] == "--node-rw":
        args = sys.argv[2:]
        if args[0] == "--preserve-container":
            preserve_container = True
            args = args[1:]
        else:
            preserve_container = False
        node_mac = args[0]
        image_id = long_image_id(args[1])
        image_fullname = args[2]
        log_print = functools.partial(node_rw_print, node_mac)
        log_print("un-mounting...")
        node_rw_umount(log_print, preserve_container,
                       node_mac, image_id, image_fullname)
        log_print("un-mounting done")
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    run()
