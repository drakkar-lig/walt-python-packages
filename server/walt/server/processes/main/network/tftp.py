import os, shutil, tarfile
from walt.common.tools import failsafe_makedirs, failsafe_symlink
from pkg_resources import resource_filename
from pathlib import Path

TFTP_ROOT = '/var/lib/walt/'
PXE_PATH = TFTP_ROOT + 'pxe/'
NODES_PATH = TFTP_ROOT + 'nodes/'
TFTP_STANDBY_DIR = Path(TFTP_ROOT + 'tftp-standby')

def prepare():
    if not Path(PXE_PATH).exists():
        failsafe_makedirs(PXE_PATH)
        orig_path = resource_filename(__name__, 'walt-x86-undionly.kpxe')
        shutil.copy(orig_path, PXE_PATH)
    if not TFTP_STANDBY_DIR.exists():
        archive_path = resource_filename(__name__, 'tftp-standby.tar.gz')
        with tarfile.open(archive_path) as tar:
            tar.extractall(str(TFTP_STANDBY_DIR.parent))

def update(db, images):
    # create dir if it does not exist yet
    failsafe_makedirs(NODES_PATH)
    # list existing entries, in case some of them are obsolete
    invalid_entries = set(f for f in os.listdir(NODES_PATH))
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
    for db_node in db.select('nodes'):
        mac = db_node.mac
        model = db_node.model
        mac_dash = mac.replace(':', '-')
        device = db.select_unique('devices', mac=mac)
        failsafe_makedirs(NODES_PATH + mac)
        failsafe_makedirs(NODES_PATH + mac + '/persist')
        for ln_name in (mac_dash, device.ip, device.name):
            failsafe_symlink(NODES_PATH + mac, NODES_PATH + ln_name, force_relative=True)
            # this entry is valid
            invalid_entries.discard(ln_name)
        invalid_entries.discard(mac)
        if db_node.image is None:
            continue
        image = images[db_node.image]
        if not image.ready:
            continue
        image_path = image.mount_path
        if image_path is None:
            # when overwritting a mounted image, we umount it even if it is in use,
            # and we get here.
            continue
        failsafe_symlink(image_path, NODES_PATH + mac + '/fs', force_relative=True)
        # link to boot files stored inside the image
        failsafe_symlink(image_path + '/boot/' + model,
                        NODES_PATH + mac + '/tftp', force_relative=True)
    # if there are still values in variable invalid_entries,
    # we can remove the corresponding entry
    for entry in invalid_entries:
        entry = NODES_PATH + entry
        if os.path.isdir(entry) and not os.path.islink(entry):
            shutil.rmtree(entry)
        else:
            os.remove(entry)

def cleanup(db):
    # walt-server-daemon is going down, which will cause nodes to reboot.
    # Some node models may hang forever in the boot procedure if they cannot
    # download appropriate boot files using TFTP. This is the case for rpi 3b+
    # and later boards, whose firmware is able to boot over the network without
    # a SD card: if the firmware is not able to download the TFTP files, it
    # will hang. In this cleanup procedure, we replace the target of the 'tftp'
    # symlink, which normally targets '[image-root]:/boot/<model>', by
    # '/var/lib/walt/tftp-standby/<model>', where appropriate boot files can
    # be found. These boot files will cause the node to continuously reboot
    # until walt-server-daemon is back.
    if not TFTP_STANDBY_DIR.exists():
        # There was an issue in startup code before tftp.prepare() could be called
        return
    for db_node in db.select('nodes'):
        mac = db_node.mac
        model = db_node.model
        standby_target = TFTP_STANDBY_DIR / model
        standby_target.mkdir(parents=True, exist_ok=True)
        failsafe_symlink(str(standby_target),
                         NODES_PATH + mac + '/tftp', force_relative=True)
