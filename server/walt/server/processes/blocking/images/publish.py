from __future__ import annotations

import typing

from walt.server.processes.blocking.images.metadata import \
                        update_user_metadata_for_image

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server


# this implements walt image publish
def publish(requester, server: Server, hub, dh_peer, auth_conf, image_fullname):
    # prepare
    labels = server.images.store[image_fullname].get_labels()
    # push image
    success = hub.push(image_fullname, dh_peer, auth_conf, requester)
    if not success:
        return False
    # update user metadata ('walt_metadata' image on user's hub account)
    update_user_metadata_for_image(hub, dh_peer, auth_conf,
                                   requester, image_fullname, labels)
    return True
