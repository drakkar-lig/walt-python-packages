from __future__ import annotations

import typing

from walt.server.processes.main.images.image import validate_image_name, format_image_fullname

if typing.TYPE_CHECKING:
    from walt.server.processes.main.repository import WalTLocalRepository


def do_rename(images, repository: WalTLocalRepository, image, new_name):
    new_fullname = format_image_fullname(image.user, new_name)
    # rename the image
    image.filesystem.close()
    repository.tag(image.fullname, new_fullname)
    repository.rmi(image.fullname)
    # update the store
    images.rename(image.fullname, new_fullname)

def rename(images, repositories: Repositories, requester, image_name, new_name):
    if not validate_image_name(requester, new_name):
        return
    image = images.get_user_unused_image_from_name(requester, image_name)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_name(requester, new_name, expected=False):
            do_rename(images, repositories, image, new_name)
