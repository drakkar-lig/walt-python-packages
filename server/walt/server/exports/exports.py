import numpy as np
import pickle
import shutil
import tarfile

from importlib.resources import files
from pathlib import Path
from walt.common.apilink import ServerAPILink
from walt.common.tools import failsafe_makedirs, failsafe_symlink
from walt.server.exports.const import TFTP_ROOT
from walt.server.exports import nfs, nbfs
from walt.server.mount.tools import detect_mounts

PXE_PATH = TFTP_ROOT / "pxe"
NODES_PATH = TFTP_ROOT / "nodes"
TFTP_STATIC_DIR = TFTP_ROOT / "tftp-static"
TFTP_STATIC_DIR_TS = 1741598952
NODE_PROBING_PATH = NODES_PATH / 'probing'
NODE_PROBING_TFTP_PATH = NODE_PROBING_PATH / 'tftp'
EXPORTS_STATUS_PATH = TFTP_ROOT / "status.pickle"


def save_exports_status(status):
    EXPORTS_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORTS_STATUS_PATH.write_bytes(pickle.dumps(status))


def is_real_dir(path):
    return not path.is_symlink() and path.is_dir()


def _wf_check_retcode(wf, verb, retcode, **env):
    if retcode != 0:
        raise Exception(f"Failed to {verb} an image")
    wf.next()


def _wf_unmount(self, wf, image_id, deadlines, ev_loop, **env):
    deadlines.pop(image_id, None)
    ev_loop.do(
            f"walt-image-umount {image_id}",
            functools.partial(_wf_check_retcode, wf, "umount"),
            silent=False)


def _wf_unmount_images(self, wf, image_ids_pending_unmount, **env):
    if len(image_ids_pending_unmount) > 0:
        steps = []
        for image_id in image_ids_pending_unmount:
            step = functools.partial(_wf_unmount, image_id=image_id)
            steps.append(step)
        wf.insert_parallel_steps(steps)
    wf.next()


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


def revert_to_empty_status():
    print("invalid or missing status file, resetting.")
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
    # detect OS image mounts and initialize the status with that
    status = set()
    image_ids, node_rw_mounts = detect_mounts()
    if len(image_ids) > 0:
        status |= ("MOUNT-IMAGE " + image_ids)
    if len(node_rw_mounts) > 0:
        status |= ("MOUNT-NODE-RW " + nodes_rw.mac + " " +
                   nodes_rw.image_id + " " + nodes_rw.image)
    save_exports_status(status)
    return status


def prepare():
    import walt.server.exports
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
    tftp_standby = TFTP_ROOT / "tftp-standby"
    if tftp_standby.exists():
        shutil.rmtree(str(tftp_standby))


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
#
# about case cleanup=True:
# walt-server-daemon is going down, which will cause nodes to reboot.
# Some node models may hang forever in the boot procedure if they cannot
# download appropriate boot files using TFTP. This is the case for rpi 3b+
# and later boards, whose firmware is able to boot over the network without
# a SD card: if the firmware is not able to download the TFTP files, it
# will hang. In this case, we replace the target of the 'tftp'
# symlink, which normally targets '[image-root]:/boot/<model>', by
# '/var/lib/walt/tftp-static', where appropriate boot files can
# be found. These boot files will cause the node to continuously reboot
# until walt-server-daemon is back.

def update(cleanup=False):
    if EXPORTS_STATUS_PATH.exists():
        old_status = pickle.loads(EXPORTS_STATUS_PATH.read_bytes())
    else:
        old_status = revert_to_empty_status()
    # -- query exports info from main server daemon
    with ServerAPILink("localhost", "SSAPI") as server:
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
        "SYMLINK fs_rw/" + rw_nodes.image_id + "/" + rw_nodes.image
        "/merged " + rw_nodes.mac + "/fs")
    # -- declare tftp symlinks
    # if this function was called as part of the cleanup procedure,
    # the symlink <mac>/tftp is redirected to TFTP_STATIC_DIR
    # (see comment about case cleanup=True above)
    if cleanup:
        tftp_symlinks = ("SYMLINK ../../tftp-static " +
                         db_nodes.mac + "/tftp")
    else:
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
    image_mounts = ("MOUNT-IMAGE " + np.unique(db_nodes.image_id))
    # node rw-mounts
    nodes_rw_mask = (db_nodes.boot_mode == 'network-persistent')
    nodes_rw = db_nodes[nodes_rw_mask]
    node_rw_mounts = ("MOUNT-NODE-RW " + nodes_rw.mac + " " +
                      nodes_rw.image_id + " " + nodes_rw.image)
    # -- compile the new status
    status = set(np.concatenate((
        mac_dirs, mac_dash_symlinks, ip_symlinks, name_symlinks,
        fs_ro_symlinks, fs_rw_symlinks, tftp_symlinks, persist_symlinks,
        free_ip_symlinks, unknown_rpis_symlinks,
        image_mounts, node_rw_mounts), dtype=object))
    if status == old_status:
        # nothing changed
        return
    TODO :
    gerer les directives MOUNT et NODE-RW-MOUNT, en demontage
    * et en remontage. Attention dans l ordre il faut :
      1-monter 2-update nfs/nbfs 3-demonter
      le probleme c est pour les montages au meme endroit mais
      differents dans l ancien status et le nouveau.
      Pour simplifier on met le point de montage sur un repertoire
      <node>/fs-rw/<image-id>/<img-fullname>/merged, comme ça
      c est toujours le meme a cet endroit.
    * executable "walt-image-mount" a adapter avec 2 options
      "--image" ou "--node-rw".
    while True:
        valid_status = True
        # -- remove entries of old status no longer present
        # note: we sort to ensure SYMLINK directives are first
        for directive in sorted(old_status - status, reverse=True):
            args = directive.split()
            if args[0] == "SYMLINK":
                if not (NODES_PATH / args[2]).is_symlink():
                    # the status file contains invalid information
                    valid_status = False
                    break
                #print(f"tftp: remove {args[2]}")
                (NODES_PATH / args[2]).unlink()
            elif args[0] == "DIR":
                if not is_real_dir(NODES_PATH / args[1]):
                    # the status file contains invalid information
                    valid_status = False
                    break
                #print(f"tftp: remove {args[1]}")
                shutil.rmtree(NODES_PATH / args[1])
        if not valid_status:
            old_status = revert_to_empty_status()
            continue
        # -- add new entries
        # notes:
        # * we sort to ensure DIR directives are first
        # * some dir entries might already be present because we kept
        #   persist_dirs, persist_dir, networks, disks subdirs in prepare() above.
        for directive in sorted(status - old_status):
            args = directive.split()
            if args[0] == "DIR":
                #print(f"tftp: create {args[1]}")
                mac_dir_path = NODES_PATH / args[1]
                mac_dir_path.mkdir(exist_ok=True)
            elif args[0] == "SYMLINK":
                if (NODES_PATH / args[2]).exists():
                    # the status file contains invalid information
                    valid_status = False
                    break
                #print(f"tftp: create {args[2]}")
                symlink_path = NODES_PATH / args[2]
                mac_dir_path = symlink_path.parent
                target_path = mac_dir_path / args[1]
                # automatically move <mac>/persist_dir (older walt version)
                # to <mac>/persist_dirs/<owner>, or just create
                # <mac>/persist_dirs/<owner> if missing.
                if not target_path.exists():
                    if target_path.parent.name == "persist_dirs":
                        persist_dir_path = mac_dir_path / "persist_dir"
                        if persist_dir_path.exists():
                            target_path.parent.mkdir(exist_ok=True)
                            persist_dir_path.rename(target_path)
                        else:
                            target_path.mkdir(parents=True)
                symlink_path.symlink_to(args[1])
        if not valid_status:
            old_status = revert_to_empty_status()
            continue
        # -- save the new status
        save_exports_status(status)
        return  # ok


def cleanup():
    update(cleanup=True)
