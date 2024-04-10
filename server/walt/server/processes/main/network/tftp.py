import os
import numpy as np
import pickle
import shutil
import tarfile
from pathlib import Path

from pkg_resources import resource_filename
from walt.common.tools import failsafe_makedirs, failsafe_symlink
from walt.server.tools import get_server_ip, get_walt_subnet

TFTP_ROOT = "/var/lib/walt/"
PXE_PATH = TFTP_ROOT + "pxe/"
NODES_PATH = TFTP_ROOT + "nodes/"
TFTP_STATIC_DIR = Path(TFTP_ROOT + "tftp-static")
NODE_PROBING_PATH = Path(NODES_PATH) / 'probing'
TFTP_STATUS_PATH = Path(NODES_PATH) / "status.pickle"
TFTP_STATUS = None


def save_tftp_status():
    TFTP_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TFTP_STATUS_PATH.write_bytes(pickle.dumps(TFTP_STATUS))


def is_real_dir(path):
    return not path.is_symlink() and path.is_dir()


def revert_to_empty_status():
    global TFTP_STATUS
    print("tftp: invalid or missing status file, resetting.")
    # revert to an empty status and remove the previous content,
    # except persist_dir, networks, disks if they exist
    if Path(NODES_PATH).exists():
        for node_entry in list(Path(NODES_PATH).iterdir()):
            if is_real_dir(node_entry):
                # if <mac>/persist is a directory, rename it to 'persist_dir'
                # (compatibility with older walt code)
                persist_entry = (node_entry / "persist")
                if persist_entry.is_dir():
                    persist_entry.rename("persist_dir")
                for node_dir_entry in list(node_entry.iterdir()):
                    if node_dir_entry.name not in (
                            "persist_dir", "networks", "disks"):
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
    if not Path(PXE_PATH).exists():
        failsafe_makedirs(PXE_PATH)
        orig_path = resource_filename(__name__, "walt-x86-undionly.kpxe")
        shutil.copy(orig_path, PXE_PATH)
    if not TFTP_STATIC_DIR.exists():
        archive_path = resource_filename(__name__, "tftp-static.tar.gz")
        with tarfile.open(archive_path) as tar:
            tar.extractall(str(TFTP_STATIC_DIR.parent))
    if TFTP_STATUS_PATH.exists():
        TFTP_STATUS = pickle.loads(TFTP_STATUS_PATH.read_bytes())
    else:
        revert_to_empty_status()
    if not NODE_PROBING_PATH.exists():
        NODE_PROBING_PATH.mkdir(parents=True)
        failsafe_symlink(
            str(TFTP_STATIC_DIR),
            str(NODE_PROBING_PATH / "tftp"),
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
# /var/lib/walt/nodes/<mac>/persist_dir in the usual situation
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

def update(db, images, cleanup=False):
    global TFTP_STATUS
    db_nodes = db.execute("""
                SELECT d.mac, d.ip, d.name, d.conf, n.model, n.image,
                    REPLACE(d.mac, ':', '-') as mac_dash,
                    COALESCE((d.conf->'mount.persist')::bool, true) as persist
                FROM devices d, nodes n
                WHERE d.mac = n.mac""")
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
        "SYMLINK persist_dir " + db_nodes.mac[mask_persist] + "/persist")
    persist_ko_symlinks = (
        "SYMLINK forbidden_dir " + db_nodes.mac[~mask_persist] + "/persist")
    # -- declare symlinks to node-probing dir for unallocated ips
    # Raspberry pi 3b+ boards do not implement the whole DHCP handshake and
    # try to use the IP offered directly without requesting it. So in case the
    # device is new, the dhcp commit event is never called, walt-dhcp-event is
    # never run, and the server is not aware of the new device trying to boot.
    # That's why we create a link nodes/<free-ip>/tftp -> ../../tftp-static
    # for all remaining free ips. This will allow the new rpi board to find
    # the firmware files and u-boot bootloader binary properly. Running u-boot
    # will allow to detect the rpi model and redo the DHCP handshake properly,
    # so the server is aware of it and can direct next requests to a default
    # image.
    subnet = get_walt_subnet()
    free_ips = set(str(ip) for ip in subnet.hosts())
    server_ip = get_server_ip()
    free_ips.discard(server_ip)
    free_ips -= set(db_nodes.ip)
    free_ips = np.array(list(free_ips), dtype=object)
    free_ip_symlinks = f"SYMLINK probing " + free_ips
    # -- compile the new status
    status = set(np.concatenate((
        mac_dirs, mac_dash_symlinks, ip_symlinks, name_symlinks,
        fs_symlinks, tftp_symlinks, persist_ok_symlinks, persist_ko_symlinks,
        free_ip_symlinks), dtype=object))
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
        # * some dir entries might already be present because
        #   we kept persist_dir, networks, disks subdirs in prepare() above.
        for directive in sorted(status - TFTP_STATUS):
            args = directive.split()
            if args[0] == "DIR":
                #print(f"tftp: create {args[1]}")
                mac_dir_path = Path(NODES_PATH + args[1])
                mac_dir_path.mkdir(exist_ok=True)
                (mac_dir_path / "persist_dir").mkdir(exist_ok=True)
            elif args[0] == "SYMLINK":
                if Path(NODES_PATH + args[2]).exists():
                    # the status file contains invalid information
                    valid_status = False
                    break
                #print(f"tftp: create {args[2]}")
                Path(NODES_PATH + args[2]).symlink_to(args[1])
        if not valid_status:
            revert_to_empty_status()
            continue
        # -- save the new status
        TFTP_STATUS = status
        save_tftp_status()
        return  # ok
