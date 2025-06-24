import os
import numpy as np
import pickle
import shutil
import tarfile
from pathlib import Path

from importlib.resources import files
from walt.common.tools import failsafe_makedirs, failsafe_symlink
from walt.server.tools import get_server_ip, get_walt_subnet
from walt.server.tools import get_rpi_foundation_mac_vendor_ids

TFTP_ROOT = "/var/lib/walt/"
PXE_PATH = TFTP_ROOT + "pxe/"
NODES_PATH = TFTP_ROOT + "nodes/"
TFTP_STATIC_DIR = Path(TFTP_ROOT + "tftp-static")
TFTP_STATIC_DIR_TS = 1741598952
NODE_PROBING_PATH = Path(NODES_PATH) / 'probing'
NODE_PROBING_TFTP_PATH = NODE_PROBING_PATH / 'tftp'
TFTP_STATUS_PATH = Path(NODES_PATH) / "status.pickle"
TFTP_STATUS = None


def save_tftp_status():
    TFTP_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TFTP_STATUS_PATH.write_bytes(pickle.dumps(TFTP_STATUS))


def is_real_dir(path):
    return not path.is_symlink() and path.is_dir()


# Note about <node>:/persist NFS target
# - on oldest installations, the target was a directory <mac>/persist;
# - later, in order to handle the new node setting "mount.persist=<bool>",
#   <mac>/persist became a symlink to a directory <mac>/persist_dir
#   or a broken target when mount.persist=false;
# - now, <mac>/persist is a symlink to <mac>/persist_dirs/<owner>,
#   or a broken target when mount.persist=false.
# This new setting allows sharing the use of the persistent directory
# of a node between several users.


def revert_to_empty_status():
    global TFTP_STATUS
    print("tftp: invalid or missing status file, resetting.")
    # revert to an empty status and remove the previous content,
    # except persist_dirs, persist_dir, networks, disks if they exist
    if Path(NODES_PATH).exists():
        for node_entry in list(Path(NODES_PATH).iterdir()):
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
                            "persist_dirs", "persist_dir", "networks", "disks"):
                        if is_real_dir(node_dir_entry):
                            shutil.rmtree(node_dir_entry)
                        else:
                            node_dir_entry.unlink()
            else:
                node_entry.unlink()
    TFTP_STATUS = set()
    save_tftp_status()


def prepare():
    global TFTP_STATUS
    import walt.server.processes.main.network
    this_dir = files(walt.server.processes.main.network)
    if not Path(PXE_PATH).exists():
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
    if TFTP_STATUS_PATH.exists():
        TFTP_STATUS = pickle.loads(TFTP_STATUS_PATH.read_bytes())
    else:
        revert_to_empty_status()
    if not NODE_PROBING_PATH.exists():
        NODE_PROBING_PATH.mkdir(parents=True)
    if not NODE_PROBING_TFTP_PATH.is_symlink():
        failsafe_symlink(
            str(TFTP_STATIC_DIR),
            str(NODE_PROBING_TFTP_PATH),
            force_relative=True
        )
    # tftp-standby is an obsolete (<8.3) directory
    tftp_standby = Path(TFTP_ROOT + "tftp-standby")
    if tftp_standby.exists():
        shutil.rmtree(str(tftp_standby))


# Note: NFSv4 needs to be able to read symlinks, thus
# the whole /var/lib/walt/nodes directory is a read-only share.
#
# If a node has its config option "mount.persist" set to false,
# removing /var/lib/walt/nodes/<mac>/persist from the exports file
# is not enough: the client mount will still be accepted, as read-only,
# because of the previous statement.
#
# That's why we actually manage a symlink at
# /var/lib/walt/nodes/<mac>/persist. The symlink targets directory
# /var/lib/walt/nodes/<mac>/persist_dirs/<owner> in the usual situation
# (mount.persist=true) and a missing path otherwise (mount.persist=false),
# in order to make the mount fail on client side.
#
# each node has a directory entry with:
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


RPI_MAC_CONDITION = " or ".join(
        f"""d.mac like '{vendor_id}:%'""" \
        for vendor_id in get_rpi_foundation_mac_vendor_ids())


WALT_SUBNET = str(get_walt_subnet())


QUERY_DEVICES_WITH_IP = f"""
SELECT d.mac, d.ip, d.name, d.type,
  REPLACE(d.mac, ':', '-') as mac_dash,
  n.model, n.image,
  split_part(n.image, '/', 1) as owner,
  ((d.type = 'node') and
   COALESCE((d.conf->'mount.persist')::bool, true)) as persist,
  ({RPI_MAC_CONDITION}) as is_rpi
FROM devices d
LEFT JOIN nodes n ON d.mac = n.mac
WHERE d.ip IS NOT NULL
  AND d.ip::inet << '{WALT_SUBNET}'::cidr
"""


def update(db, images, cleanup=False):
    global TFTP_STATUS
    db_devices = db.execute(QUERY_DEVICES_WITH_IP)
    db_nodes = db_devices[db_devices.type == 'node']
    # -- declare dirs
    mac_dirs = "DIR " + db_nodes.mac
    # -- declare ip, name and mac-dash symlinks
    mac_dash_symlinks = "SYMLINK " + db_nodes.mac + " " + db_nodes.mac_dash
    ip_symlinks = "SYMLINK " + db_nodes.mac + " " + db_nodes.ip
    name_symlinks = "SYMLINK " + db_nodes.mac + " " + db_nodes.name
    # -- declare fs and tftp symlinks
    # if this function was called as part of the cleanup procedure,
    # the symlink <mac>/tftp is redirected to TFTP_STATIC_DIR
    # (see comment about case cleanup=True above)
    metadata = images.registry.get_multiple_metadata(db_nodes.image)
    image_ids = np.fromiter((m["image_id"] for m in metadata), dtype=object)
    fs_symlinks = (
        "SYMLINK ../../images/" + image_ids + "/fs " + db_nodes.mac + "/fs")
    if cleanup:
        tftp_symlinks = ("SYMLINK ../../tftp-static " + db_nodes.mac + "/tftp")
    else:
        tftp_symlinks = (
            "SYMLINK ../../images/" + image_ids + "/fs/boot/" + db_nodes.model +
            " " + db_nodes.mac + "/tftp")
    # -- declare persist symlinks
    mask_persist = db_nodes.persist.astype(bool)
    persist_ok_symlinks = (
        "SYMLINK persist_dirs/" + db_nodes.owner[mask_persist] + " " +
        db_nodes.mac[mask_persist] + "/persist")
    persist_ko_symlinks = (
        "SYMLINK forbidden_dir " + db_nodes.mac[~mask_persist] + "/persist")
    # -- declare symlinks to node-probing dir for unallocated ips
    #    and Raspberry Pi devices of type "unknown"
    # Raspberry pi 3b+ boards do not implement the whole DHCP handshake and
    # try to use the IP offered directly without requesting it. So in case the
    # device is new, the dhcp commit event is never called, walt-dhcp-event is
    # never run, and the server is not aware of the new device trying to boot.
    # That's why we create a link nodes/<free-ip>/tftp -> ../../tftp-static
    # for all remaining free ips. This will allow the new rpi board to find
    # the firmware files and u-boot bootloader binary properly. Running u-boot
    # will then allow to detect the rpi model and redo the DHCP handshake
    # properly, so the server is aware of it and can direct next requests to
    # a default image.
    subnet = get_walt_subnet()
    free_ips = set(str(ip) for ip in subnet.hosts())
    server_ip = get_server_ip()
    free_ips.discard(server_ip)
    free_ips -= set(db_devices.ip)
    free_ips = np.array(list(free_ips), dtype=object)
    free_ip_symlinks = "SYMLINK probing " + free_ips
    # Another corner case is when a Raspberry Pi board was first connected to
    # the WALT network but equipped with a local OS on its SD card. In this
    # case it will not follow the bootup procedure of WALT nodes and will be
    # registered as a device of "unknown" type. Later, if trying to boot the
    # same board without the SD card, we need to have the TFTP links to the
    # "probing" dir ready too, to allow WALT network bootup.
    unknown_rpis_mask = (db_devices.type == 'unknown')
    unknown_rpis_mask &= db_devices.is_rpi.astype(bool)
    unknown_rpis = db_devices[unknown_rpis_mask]
    unknown_rpis_symlinks = np.concatenate((
            "SYMLINK probing " + unknown_rpis.ip,
            "SYMLINK probing " + unknown_rpis.mac,
            "SYMLINK probing " + unknown_rpis.mac_dash,
            "SYMLINK probing " + unknown_rpis.name), dtype=object)
    # -- compile the new status
    status = set(np.concatenate((
        mac_dirs, mac_dash_symlinks, ip_symlinks, name_symlinks,
        fs_symlinks, tftp_symlinks, persist_ok_symlinks, persist_ko_symlinks,
        free_ip_symlinks, unknown_rpis_symlinks), dtype=object))
    if status == TFTP_STATUS:
        # nothing changed
        return
    while True:
        valid_status = True
        # -- remove entries of old status no longer present
        # note: we sort to ensure SYMLINK directives are first
        for directive in sorted(TFTP_STATUS - status, reverse=True):
            args = directive.split()
            if args[0] == "SYMLINK":
                if not Path(NODES_PATH + args[2]).is_symlink():
                    # the status file contains invalid information
                    valid_status = False
                    break
                #print(f"tftp: remove {args[2]}")
                Path(NODES_PATH + args[2]).unlink()
            elif args[0] == "DIR":
                if not is_real_dir(Path(NODES_PATH + args[1])):
                    # the status file contains invalid information
                    valid_status = False
                    break
                #print(f"tftp: remove {args[1]}")
                shutil.rmtree(NODES_PATH + args[1])
        if not valid_status:
            revert_to_empty_status()
            continue
        # -- add new entries
        # notes:
        # * we sort to ensure DIR directives are first
        # * some dir entries might already be present because we kept
        #   persist_dirs, persist_dir, networks, disks subdirs in prepare() above.
        for directive in sorted(status - TFTP_STATUS):
            args = directive.split()
            if args[0] == "DIR":
                #print(f"tftp: create {args[1]}")
                mac_dir_path = Path(NODES_PATH + args[1])
                mac_dir_path.mkdir(exist_ok=True)
            elif args[0] == "SYMLINK":
                if Path(NODES_PATH + args[2]).exists():
                    # the status file contains invalid information
                    valid_status = False
                    break
                #print(f"tftp: create {args[2]}")
                symlink_path = Path(NODES_PATH + args[2])
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
            revert_to_empty_status()
            continue
        # -- save the new status
        TFTP_STATUS = status
        save_tftp_status()
        return  # ok
