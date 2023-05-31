from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from walt.server.processes.main.registry import WalTLocalRegistry


def remove(images, registry: WalTLocalRegistry, requester, image_name):
    image = images.get_user_unused_image_from_name(requester, image_name)
    if image:  # otherwise issue is already reported
        image.filesystem.close()
        registry.rmi(image.fullname)
        images.remove(image.fullname)
        return True
    else:
        return False
