import numpy as np
import pickle
import shelve
import shutil
import tarfile

from importlib.resources import files
from pathlib import Path
from time import time
from walt.common.tools import (
        failsafe_makedirs,
        failsafe_symlink,
)
from walt.server.exports.const import(
        PXE_PATH,
        NODES_PATH,
        TFTP_STATIC_DIR,
        TFTP_STATIC_DIR_TS,
        NODE_PROBING_PATH,
        NODE_PROBING_TFTP_PATH,
        EXPORTS_STATUS_PATH,
        MOUNT_DEADLINES_PATH,
        OBSOLETE_TFTP_STANDBY_PATH,
        OBSOLETE_PERSIST_EXPORTS_PATH,
)
from walt.server.exports.ops.dirs import wf_add_dirs, wf_remove_dirs
from walt.server.exports.ops.symlinks import (
        wf_add_symlinks,
        wf_remove_symlinks,
)
from walt.server.exports.ops.mounts import (
        wf_add_mounts,
        wf_remove_mounts,
)
from walt.server.exports.ops.nfs import (
        wf_compute_nfs_info,
        wf_update_nfs,
        wf_cleanup_nfs,
)
from walt.server.exports.ops.nbfs import (
        wf_update_nbfs,
        wf_cleanup_nbfs,
)
from walt.server.mount.tools import (
        detect_mounts,
        discard_mount_images,
        mount_exists,
        get_image_mount_path,
        get_node_rw_mount_path,
        get_node_rw_relative_mount_path,
)
from walt.server.tools import SSAPILink, ConcurrentShelve
from walt.server.workflow import Workflow


def save_exports_status(status):
    EXPORTS_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORTS_STATUS_PATH.write_bytes(pickle.dumps(status))


def wf_save_exports_status(wf, new_status, **env):
    save_exports_status(new_status)
    wf.next()


def is_real_dir(path):
    return not path.is_symlink() and path.is_dir()


# Note about <node>:/persist NFS target
# - on oldest installations, the target was a directory <mac>/persist;
# - later, in order to handle the new node setting "mount.persist=<bool>",
#   <mac>/persist became a symlink to a directory <mac>/persist_dir
#   or a broken target when mount.persist=false;
# - then, <mac>/persist became a symlink to <mac>/persist_dirs/<owner>,
#   or a broken target when mount.persist=false.
# - now, <mac>/persist is always a symlink to <mac>/persist_dirs/<owner>,
#   (the variable walt_persist_path the node gets by running
#    walt-fetch-node-config is empty when mount.persist=false,
#    so the mount is bypassed.)
# This new setting allows sharing the use of the persistent directory
# of a node between several users.

# When the last node using an image is associated to another image,
# this previous image should be unmounted since it is not used anymore.
# however, if this image defines /bin/walt-reboot, rebooting the node
# involves code from this previous image. In order to allow this pattern,
# we implement a grace period before an unused image is really unmounted.
# 1st call to walt-update-exports defines a deadline; next calls verify
# if this deadline is reached and if true unmount the image.
# If ever an image is reused before the grace time is expired, then the
# deadline is removed.

MOUNT_GRACE_TIME = 60
MOUNT_GRACE_TIME_MARGIN = 10
# shelve.open() appends extension '.db' to the path.
# But we defined MOUNT_DEADLINES_PATH with this extension too
# in const.py, to help the reader find it easily on the filesystem.
deadlines = ConcurrentShelve(MOUNT_DEADLINES_PATH.with_suffix(""))

def apply_grace_time_period(directive):
    deadline = deadlines.get(directive)
    curr_time = time()
    if deadline is None:
        # first time check: set the deadline value
        deadlines[directive] = curr_time + MOUNT_GRACE_TIME
        return True
    else:
        # next checks: check if the deadline is reached
        if curr_time < deadline:
            # deadline not reached, still in the grace time period
            return True
        else:
            # deadline was reached
            del deadlines[directive]
            return False


def discard_grace_time_of_directives(directives):
    directives = set(deadlines.keys()) & set(directives)
    for directive in directives:
        del deadlines[directive]


def get_grace_time_recall():
    vals = list(deadlines.values())
    if len(vals) > 0:
        return min(vals) + MOUNT_GRACE_TIME_MARGIN
    else:
        return None


def detect_mounts_status():
    status = set()
    image_mounts, node_rw_mounts = detect_mounts()
    if len(image_mounts) > 0:
        mount_image_status = set(
                "MOUNT-IMAGE " + image_mounts.image_id + " " +
                image_mounts.size_kib.astype(str))
    else:
        mount_image_status = set()
    if len(node_rw_mounts) > 0:
        mount_node_rw_status = set("MOUNT-NODE-RW " +
                      node_rw_mounts.node_mac + " " +
                      node_rw_mounts.image_id + " " +
                      node_rw_mounts.image_fullname)
    else:
        mount_node_rw_status = set()
    return mount_image_status, mount_node_rw_status


def extract_mounts_status(status):
    status = np.array(sorted(status), str)
    mask_mounts = np.char.startswith(status, "MOUNT-IMAGE")
    mask_mounts |= np.char.startswith(status, "MOUNT-NODE-RW")
    return set(status[mask_mounts])


def revert_to_empty_status(curr_mounts_status):
    print("Invalid or missing status file, resetting.")
    # remove the previous content in /var/lib/walt/nodes,
    # except persist_dirs, persist_dir, networks, disks and fs_rw
    # if they exist.
    if NODES_PATH.exists():
        for node_entry in list(NODES_PATH.iterdir()):
            if node_entry == NODE_PROBING_PATH:
                continue  # not really a node entry
            if is_real_dir(node_entry):
                # if <mac>/persist is a directory, rename it to 'persist_dir'
                # (compatibility with older walt code)
                # the content of 'persist_dir' will then be moved to
                # 'persist_dirs/<owner>' as a later step.
                persist_entry = (node_entry / "persist")
                if is_real_dir(persist_entry):
                    persist_entry.rename("persist_dir")
                for node_dir_entry in list(node_entry.iterdir()):
                    if node_dir_entry.name not in (
                            "persist_dirs", "persist_dir",
                            "networks", "disks", "fs_rw",
                            ):
                        if is_real_dir(node_dir_entry):
                            shutil.rmtree(node_dir_entry)
                        else:
                            node_dir_entry.unlink()
            else:
                node_entry.unlink()
    # initialize the status with just current OS image mounts
    save_exports_status(curr_mounts_status)
    return curr_mounts_status


def symlink_already_there(sl_target, sl_path):
    if not sl_path.is_symlink():
        return False
    if not str(sl_path.readlink()) == str(sl_target):
        return False
    return True


def read_status_file(curr_mounts_status):
    if EXPORTS_STATUS_PATH.exists():
        old_status = pickle.loads(EXPORTS_STATUS_PATH.read_bytes())
        old_mounts_status = extract_mounts_status(old_status)
        if old_mounts_status != curr_mounts_status:
            print("Saved exports state does not match detected mounts.")
            old_status = revert_to_empty_status(curr_mounts_status)
    else:
        print("Exports state file not found.")
        old_status = revert_to_empty_status(curr_mounts_status)
    return old_status


def prepare():
    import walt.server.exports
    deadlines.clear()
    this_dir = files(walt.server.exports)
    if not PXE_PATH.exists():
        failsafe_makedirs(PXE_PATH)
        orig_path = this_dir / "walt-x86-undionly.kpxe"
        shutil.copy(str(orig_path), PXE_PATH)
    if TFTP_STATIC_DIR.exists():
        static_dir_ts = 0
        date_file = TFTP_STATIC_DIR / "walt.date"
        if date_file.exists():
            static_dir_ts = int(date_file.read_text().splitlines()[-1])
        if static_dir_ts < TFTP_STATIC_DIR_TS:
            # obsolete static dir, remove it (will be recreated below)
            shutil.rmtree(TFTP_STATIC_DIR)
    if not TFTP_STATIC_DIR.exists():
        archive_path = this_dir / "tftp-static.tar.gz"
        with tarfile.open(str(archive_path)) as tar:
            tar.extractall(str(TFTP_STATIC_DIR.parent))
    if not NODE_PROBING_PATH.exists():
        NODE_PROBING_PATH.mkdir(parents=True)
    if not NODE_PROBING_TFTP_PATH.is_symlink():
        failsafe_symlink(
            str(TFTP_STATIC_DIR),
            str(NODE_PROBING_TFTP_PATH),
            force_relative=True
        )
    # tftp-standby is an obsolete (<8.3) directory
    if OBSOLETE_TFTP_STANDBY_PATH.exists():
        shutil.rmtree(str(TFTP_STANDBY_PATH))
    # persist exports were previously (<11.0) in a separate file
    OBSOLETE_PERSIST_EXPORTS_PATH.unlink(missing_ok=True)


# Each node has a directory entry with:
# - a link called "fs" to the image filesystem root
# - a link called "tftp" to a directory of boot files stored per-model in the image
# - a directory called "persist" which is mounted at /persist on the node
# The name of this dir is the mac address of the node,
# written <hh>:<hh>:<hh>:<hh>:<hh>:<hh>.
# For compatibility with different network bootloaders
# we also provide 3 links to this directory:
# - mac address written <hh>-<hh>-<hh>-<hh>-<hh>-<hh>
# - ipv4 address (dotted quad notation)
# - walt node name

def update(auto_recall=False):
    mount_image_status, mount_node_rw_status = detect_mounts_status()
    curr_mounts_status = mount_image_status | mount_node_rw_status
    old_status = read_status_file(curr_mounts_status)
    # -- query exports info from main server daemon
    with SSAPILink() as server:
        db_nodes, unknown_rpis, free_ips = server.get_exports_info()
    # -- declare dirs
    mac_dirs = "DIR " + db_nodes.mac
    # -- declare ip, name and mac-dash symlinks
    mac_dash_symlinks = "SYMLINK " + db_nodes.mac + " " + db_nodes.mac_dash
    ip_symlinks = "SYMLINK " + db_nodes.mac + " " + db_nodes.ip
    name_symlinks = "SYMLINK " + db_nodes.mac + " " + db_nodes.name
    # -- declare fs symlinks
    rw_nodes_mask = (db_nodes.boot_mode == "network-persistent")
    rw_nodes = db_nodes[rw_nodes_mask]
    ro_nodes = db_nodes[~rw_nodes_mask]
    fs_ro_symlinks = (
        "SYMLINK ../../images/" + ro_nodes.image_id +
        "/fs " + ro_nodes.mac + "/fs")
    fs_rw_symlinks = (
        "SYMLINK " +
        get_node_rw_relative_mount_path(
            rw_nodes.image_id,
            rw_nodes.image
        ) + " " +
        rw_nodes.mac + "/fs")
    # -- declare tftp symlinks
    tftp_symlinks = (
        "SYMLINK fs/boot/" + db_nodes.model +
        " " + db_nodes.mac + "/tftp")
    # -- declare persist symlinks
    persist_symlinks = (
        "SYMLINK persist_dirs/" + db_nodes.owner + " " +
        db_nodes.mac + "/persist")
    # -- declare symlinks to node-probing dir for unallocated ips
    #    and Raspberry Pi devices of type "unknown"
    # Raspberry pi 3b+ boards do not implement the whole DHCP handshake and
    # try to use the IP offered directly without requesting it. So in case
    # the device is new, the dhcp commit event is never called,
    # walt-dhcp-event is never run, and the server is not aware of the
    # new device trying to boot.
    # That's why we create a link nodes/<free-ip>/tftp -> ../../tftp-static
    # for all remaining free ips. This will allow the new rpi board to find
    # the firmware files and u-boot bootloader binary properly.
    # Running u-boot will then allow to detect the rpi model and redo the
    # DHCP handshake properly, so the server is aware of it and can direct
    # next requests to a default image.
    free_ip_symlinks = "SYMLINK probing " + free_ips
    # Another corner case is when a Raspberry Pi board was first connected to
    # the WALT network but equipped with a local OS on its SD card. In this
    # case it will not follow the bootup procedure of WALT nodes and will be
    # registered as a device of "unknown" type. Later, if trying to boot the
    # same board without the SD card, we need to have the TFTP links to the
    # "probing" dir ready too, to allow WALT network bootup.
    unknown_rpis_symlinks = np.concatenate((
            "SYMLINK probing " + unknown_rpis.ip,
            "SYMLINK probing " + unknown_rpis.mac,
            "SYMLINK probing " + unknown_rpis.mac_dash,
            "SYMLINK probing " + unknown_rpis.name), dtype=object)
    # image mounts
    image_ids, uniq_idx = np.unique(db_nodes.image_id, return_index=True)
    image_sizes = db_nodes.image_size_kib[uniq_idx].astype(str)
    image_mounts = ("MOUNT-IMAGE " + image_ids + " " + image_sizes)
    # node rw-mounts
    node_rw_mounts = ("MOUNT-NODE-RW " +
                      rw_nodes.mac + " " +
                      rw_nodes.image_id + " " +
                      rw_nodes.image)
    # if we were in the grace time period before unmounting a mountpoint
    # but we now need it again, discard its grace time deadline.
    discard_grace_time_of_directives(image_mounts)
    discard_grace_time_of_directives(node_rw_mounts)
    # -- compile the new status
    status = set(np.concatenate((
        mac_dirs, mac_dash_symlinks, ip_symlinks, name_symlinks,
        fs_ro_symlinks, fs_rw_symlinks, tftp_symlinks, persist_symlinks,
        free_ip_symlinks, unknown_rpis_symlinks,
        image_mounts, node_rw_mounts), dtype=object))
    if status == old_status:
        # nothing changed
        return
    while True:
        removed_symlinks, removed_dirs = [], []
        added_symlinks, added_dirs = [], []
        added_mounts, removed_mounts = [], []
        valid_status = True
        if valid_status:
            # -- check entries of old status no longer present
            for directive in old_status - status:
                args = directive.split()
                if args[0] == "SYMLINK":
                    sl_target = args[1]
                    sl_path = (NODES_PATH / args[2])
                    if not symlink_already_there(sl_target, sl_path):
                        # the status file contains invalid information
                        print("Exports state file "
                              "includes a missing symlink.")
                        valid_status = False
                        break
                    removed_symlinks.append(args[2])
                elif args[0] == "DIR":
                    if not is_real_dir(NODES_PATH / args[1]):
                        # the status file contains invalid information
                        print("Exports state file "
                              "references a missing directory.")
                        valid_status = False
                        break
                    removed_dirs.append(NODES_PATH / args[1])
                elif args[0] == "MOUNT-IMAGE":
                    if not mount_exists(get_image_mount_path(args[1])):
                        # the status file contains invalid information
                        print("Exports state file "
                              "references a missing image mount.")
                        valid_status = False
                        break
                    if apply_grace_time_period(directive):
                        status.add(directive)
                    else:
                        removed_mounts.append(args)
                elif args[0] == "MOUNT-NODE-RW":
                    params = tuple(args[1:])
                    mount_path = get_node_rw_mount_path(*params)
                    if not mount_exists(mount_path):
                        # the status file contains invalid information
                        print("Exports state file "
                              "references a missing node-rw mount.")
                        valid_status = False
                        break
                    if apply_grace_time_period(directive):
                        status.add(directive)
                    else:
                        removed_mounts.append(args)
        if valid_status:
            # -- check new entries
            for directive in sorted(status - old_status):
                args = directive.split()
                if args[0] == "DIR":
                    added_dirs.append(args[1])
                elif args[0] == "SYMLINK":
                    sl_target = args[1]
                    sl_path = (NODES_PATH / args[2])
                    if symlink_already_there(sl_target, sl_path):
                        # the status file contains invalid information
                        print("Exports state file "
                              "misses an existing symlink.")
                        valid_status = False
                        break
                    added_symlinks.append((args[1], args[2]))
                elif args[0] == "MOUNT-IMAGE":
                    if mount_exists(get_image_mount_path(args[1])):
                        # the status file contains invalid information
                        print("Exports state file "
                              "misses an existing image mount.")
                        valid_status = False
                        break
                    added_mounts.append(args)
                elif args[0] == "MOUNT-NODE-RW":
                    params = tuple(args[1:])
                    mount_path = get_node_rw_mount_path(*params)
                    if mount_exists(mount_path):
                        # the status file contains invalid information
                        print("Exports state file "
                              "misses an existing node-rw mount.")
                        valid_status = False
                        break
                    added_mounts.append(args)
        # check if we can proceed or we need to retry
        if not valid_status:
            # loop and retry with a cleaned up status
            old_status = revert_to_empty_status(curr_mounts_status)
            continue
        # -- ok, everything seems fine, proceed with the updates
        # note: we have to do that in the correct order!
        # for instance mount -> update nfs -> umount
        wf = Workflow([
                wf_remove_symlinks,
                wf_add_dirs,
                wf_add_symlinks,
                wf_add_mounts,
                wf_compute_nfs_info,
                wf_update_nfs,
                wf_update_nbfs,
                wf_remove_mounts,
                wf_remove_dirs,
                wf_save_exports_status,
            ],
            db_nodes = db_nodes,
            new_status = status,
            removed_symlinks = removed_symlinks,
            removed_dirs = removed_dirs,
            added_symlinks = added_symlinks,
            added_dirs = added_dirs,
            added_mounts = added_mounts,
            removed_mounts = removed_mounts,
        )
        wf.run()
        if auto_recall:
            recall_time = get_grace_time_recall()
            if recall_time is not None:
                with SSAPILink() as server:
                    server.plan_update_exports(recall_time)
        return


# The cleanup() function is called when the walt-server-daemon is going
# down.
#
# In this case, we have to:
# 1. unmount images and node-rw mounts
# 2. clear walt-owned NFS and NBFS exports
# 3. direct 'tftp' symlinks to the 'tftp-static' directory
#
# About step 3:
# The fact walt-server-daemon is going down will cause nodes to reboot.
# Some node models may hang forever in the boot procedure if they cannot
# download appropriate boot files using TFTP. This is the case for rpi 3b+
# and later boards, whose firmware is able to boot over the network without
# a SD card: if the firmware is not able to download the TFTP files, it
# will hang. In this case, we replace the target of the 'tftp'
# symlink, which normally targets '[image-root]:/boot/<model>', by
# '/var/lib/walt/tftp-static', where appropriate boot files can
# be found. These boot files will cause the node to continuously reboot
# until walt-server-daemon is back.

def wf_discard_mount_images(wf, **env):
    discard_mount_images()
    wf.next()


def cleanup():
    mount_image_status, mount_node_rw_status = detect_mounts_status()
    curr_mounts_status = mount_image_status | mount_node_rw_status
    old_status = read_status_file(curr_mounts_status)
    status = old_status.copy()
    # remove mounts from the status
    status -= curr_mounts_status
    # replace 'tftp' links to target 'tftp-static'
    np_status = np.array(list(status), dtype=str)
    tftp_symlinks_mask = np.char.endswith(np_status, "/tftp")
    old_tftp_symlinks = np_status[tftp_symlinks_mask]
    if len(old_tftp_symlinks) > 0:
        tftp_symlink_paths = np.char.rpartition(old_tftp_symlinks, " ")[:,2]
        new_tftp_symlinks = ("SYMLINK ../../tftp-static " +
                         tftp_symlink_paths.astype(object))
        np_status[tftp_symlinks_mask] = new_tftp_symlinks
    else:
        tftp_symlink_paths = ()
    status = set(np_status)
    # verify that something really changed
    if status == old_status:
        # nothing changed
        return
    # prepare workflow steps
    removed_symlinks = set(tftp_symlink_paths)
    added_symlinks = list(zip(
        ["../../tftp-static"] * len(tftp_symlink_paths),
        tftp_symlink_paths))
    removed_mounts = list(map(str.split, curr_mounts_status))
    # when the server is stopping, we should preserve the data held
    # by node-rw containers, except if those containers were just
    # there waiting for grace time expiry.
    preserve_node_rw_data = mount_node_rw_status - set(deadlines.keys())
    preserve_node_rw_data = list(map(str.split, preserve_node_rw_data))
    # run workflow steps
    wf = Workflow([
        wf_cleanup_nfs,
        wf_cleanup_nbfs,
        wf_remove_mounts,
        wf_remove_symlinks,
        wf_add_symlinks,
        wf_save_exports_status,
        wf_discard_mount_images,
    ],
        new_status = status,
        removed_symlinks = removed_symlinks,
        added_symlinks = added_symlinks,
        removed_mounts = removed_mounts,
        preserve_node_rw_data = preserve_node_rw_data,
    )
    wf.run()
