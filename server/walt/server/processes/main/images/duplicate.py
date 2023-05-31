from __future__ import annotations

import typing

from walt.common.tools import format_image_fullname
from walt.server.processes.main.images.image import validate_image_name

if typing.TYPE_CHECKING:
    from walt.server.processes.main.registry import WalTLocalRegistry


def do_duplicate(images, registry: WalTLocalRegistry, image, new_name):
    image.filesystem.close()
    new_fullname = format_image_fullname(image.user, new_name)
    # add a tag to the image
    registry.tag(image.fullname, new_fullname)
    # update the store
    images.register_image(new_fullname)


def duplicate(images, registry: WalTLocalRegistry, requester, image_name, new_name):
    if not validate_image_name(requester, new_name):
        return False
    image = images.get_user_image_from_name(requester, image_name)
    if image:  # otherwise issue is already reported
        if not images.get_user_image_from_name(requester, new_name, expected=False):
            do_duplicate(images, registry, image, new_name)
            return True
    return False
