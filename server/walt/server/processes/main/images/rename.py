from __future__ import annotations

import typing

from walt.common.tools import format_image_fullname
from walt.server.processes.main.images.image import validate_image_name

if typing.TYPE_CHECKING:
    from walt.server.processes.main.registry import WalTLocalRegistry


def do_rename(images, registry: WalTLocalRegistry, image, new_name):
    new_fullname = format_image_fullname(image.user, new_name)
    # rename the image
    image.filesystem.close()
    registry.tag(image.fullname, new_fullname)
    registry.rmi(image.fullname)
    # update the store
    images.rename(image.fullname, new_fullname)


def rename(images, registry: WalTLocalRegistry, requester, image_name, new_name):
    if not validate_image_name(requester, new_name):
        return False
    image = images.get_user_unused_image_from_name(requester, image_name)
    if image:  # otherwise issue is already reported
        if not images.get_user_image_from_name(requester, new_name, expected=False):
            do_rename(images, registry, image, new_name)
            return True
    return False
