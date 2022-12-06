from __future__ import annotations

import typing

from walt.server.processes.blocking.repositories import \
     DockerHubClient, get_custom_registry_client
from walt.server.processes.blocking.images.metadata import \
     update_user_metadata_for_image
from walt.server import conf

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server


# this implements walt image publish
def publish(requester, server: Server, registry_label, image_fullname, **kwargs):
    if registry_label == 'hub':
        # prepare
        labels = server.images.store[image_fullname].get_labels()
        # push image
        hub = DockerHubClient()
        success = hub.push(requester, image_fullname)
        if not success:
            return False
        # update user metadata ('walt_metadata' image on user's hub account)
        update_user_metadata_for_image(requester, hub, image_fullname, labels)
        return True
    else:
        registry = get_custom_registry_client(registry_label)
        return registry.push(requester, image_fullname)
