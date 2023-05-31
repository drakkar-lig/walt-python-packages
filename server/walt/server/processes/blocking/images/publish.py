from __future__ import annotations

import typing

from walt.server.processes.blocking.images.metadata import (
    update_user_metadata_for_image,
)
from walt.server.processes.blocking.registries import (
    DockerHubClient,
    get_custom_registry_client,
)

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server


# this implements walt image publish
def publish(requester, server: Server, registry_label, image_fullname, **kwargs):
    try:
        if registry_label == "hub":
            # prepare
            labels = server.images.store[image_fullname].get_labels()
            # push image
            registry = DockerHubClient()
            success = registry.push(requester, image_fullname)
            if success:
                # update user metadata ('walt_metadata' image on user's hub account)
                update_user_metadata_for_image(
                    requester, registry, image_fullname, labels
                )
        else:
            registry = get_custom_registry_client(registry_label)
            success = registry.push(requester, image_fullname)
    except Exception:
        requester.stderr.write(
            f"Failed to communicate with {registry_label} registry. Aborted.\n"
        )
        return (False,)
    if success:
        clone_url = registry.get_origin_clone_url(requester, image_fullname)
        if clone_url.endswith(":latest"):
            clone_url = clone_url[:-7]
        return (True, clone_url)
    else:
        return (False,)
