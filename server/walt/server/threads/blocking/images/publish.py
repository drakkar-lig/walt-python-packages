from __future__ import annotations

import typing

from walt.server.threads.blocking.images.metadata import \
                        update_user_metadata_for_image

if typing.TYPE_CHECKING:
    from walt.server.threads.main.server import Server


# this implements walt image publish
def publish(requester, server: Server, dh_peer, auth_conf, image_fullname):
    # push image
    server.repositories.hub.push(image_fullname, dh_peer, auth_conf, requester)
    # update user metadata ('walt_metadata' image on user's hub account)
    update_user_metadata_for_image(server.repositories, server.images.store, dh_peer, auth_conf,
                                   requester, image_fullname)
