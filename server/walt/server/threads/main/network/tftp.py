import os, shutil
from walt.common.tools import failsafe_makedirs, failsafe_symlink
from walt.server.threads.main.images.image import get_mount_path

NODES_PATH='/var/lib/walt/nodes/'

def update(db):
    # create dir if it does not exist yet
    failsafe_makedirs(NODES_PATH)
    # list existing entries, in case some of them are obsolete
    invalid_entries = set(f for f in os.listdir(NODES_PATH))
    # each node has a directory entry with:
    # - a link called "fs" to the image filesystem root
    # - a link called "tftp" to a directory of boot files stored per-model in the image
    # The name of this dir is the mac address of the node,
    # written <hh>:<hh>:<hh>:<hh>:<hh>:<hh>.
    # For compatibility with different network bootloaders
    # we also provide 3 links to this directory:
    # - mac address written <hh>-<hh>-<hh>-<hh>-<hh>-<hh>
    # - ipv4 address (dotted quad notation)
    # - walt node name
    for db_node in db.select('nodes'):
        if db_node.image is not None:
            image_path = get_mount_path(db_node.image)
            mac = db_node.mac
            model = db_node.model
            mac_dash = mac.replace(':', '-')
            device = db.select_unique('devices', mac=mac)
            failsafe_makedirs(NODES_PATH + mac)
            failsafe_symlink(image_path, NODES_PATH + mac + '/fs', force_relative=True)
            # link to boot files stored inside the image
            failsafe_symlink(image_path + '/boot/' + model,
                            NODES_PATH + mac + '/tftp', force_relative=True)
            for ln_name in (mac_dash, device.ip, device.name):
                failsafe_symlink(NODES_PATH + mac, NODES_PATH + ln_name, force_relative=True)
                # this entry is valid
                invalid_entries.discard(ln_name)
            invalid_entries.discard(mac)
    # if there are still values in variable invalid_entries,
    # we can remove the corresponding entry
    for entry in invalid_entries:
        entry = NODES_PATH + entry
        if os.path.isdir(entry) and not os.path.islink(entry):
            shutil.rmtree(entry)
        else:
            os.remove(entry)
