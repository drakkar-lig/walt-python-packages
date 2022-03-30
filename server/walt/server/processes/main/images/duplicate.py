from __future__ import annotations

import typing

from walt.server.processes.main.images.image import validate_image_name, format_image_fullname

if typing.TYPE_CHECKING:
    from walt.server.processes.main.repository import WalTLocalRepository


def do_duplicate(images, repository: WalTLocalRepository, image, new_name):
    image.filesystem.close()
    new_fullname = format_image_fullname(image.user, new_name)
    # add a tag to the image
    repository.tag(image.fullname, new_fullname)
    # update the store
    images.register_image(new_fullname, True)

def duplicate(images, repository: WalTLocalRepository, requester, image_name, new_name):
    if not validate_image_name(requester, new_name):
        return
    image = images.get_user_image_from_name(requester, image_name)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_name(requester, new_name, expected=False):
            do_duplicate(images, repository, image, new_name)
