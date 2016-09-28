import os
from walt.common.tools import failsafe_symlink
from walt.server.threads.main.images.image import get_mount_path

TFTP_PATH='/var/lib/walt/nodes/'

def update(db):
    # list existing links, in case some of them are obsolete
    invalid_links = set(f for f in os.listdir(TFTP_PATH))
    # each node must have a link from the tftp dir to
    # the walt image deployed on it. The name of this
    # link is the mac address of the node.
    for db_node in db.select('nodes'):
        image_path = get_mount_path(db_node.image)
        failsafe_symlink(image_path, TFTP_PATH + db_node.mac, force_relative=True)
        # this link is valid
        invalid_links.discard(db_node.mac)
    # if there are still values in variable invalid_links,
    # we can remove the corresponding link
    for l in invalid_links:
        os.remove(TFTP_PATH + l)
