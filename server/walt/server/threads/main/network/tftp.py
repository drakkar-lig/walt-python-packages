import os
from walt.common.tools import failsafe_makedirs, failsafe_symlink
from walt.server.threads.main.images.image import get_mount_path

TFTP_PATH='/var/lib/walt/nodes/'

def update(db):
    # create dir if it does not exist yet
    failsafe_makedirs(TFTP_PATH)
    # list existing links, in case some of them are obsolete
    invalid_links = set(f for f in os.listdir(TFTP_PATH))
    # each node must have a link from the tftp dir to
    # the walt image it will boot. The name of this
    # link is the mac address of the node.
    # For compatibility with different network bootloaders
    # we actually provide 2 links, corresponding to 2 different
    # ways to specify the mac address:
    # <hh>:<hh>:<hh>:<hh>:<hh>:<hh>
    # and
    # <hh>-<hh>-<hh>-<hh>-<hh>-<hh>
    for db_node in db.select('nodes'):
        if db_node.image is not None:
            image_path = get_mount_path(db_node.image)
            mac_orig = db_node.mac
            mac_dash = mac_orig.replace(':', '-')
            for mac in (mac_orig, mac_dash):
                failsafe_symlink(image_path, TFTP_PATH + mac, force_relative=True)
                # this link is valid
                invalid_links.discard(mac)
    # if there are still values in variable invalid_links,
    # we can remove the corresponding link
    for l in invalid_links:
        os.remove(TFTP_PATH + l)
