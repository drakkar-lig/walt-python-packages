from __future__ import annotations

import typing

from walt.server.threads.main.images.image import validate_image_name, format_image_fullname

if typing.TYPE_CHECKING:
    from walt.server.threads.main.repositories import Repositories


def do_rename(images, repositories: Repositories, image, new_name):
    new_fullname = format_image_fullname(image.user, new_name)
    # rename the image
    repositories.local.tag(image.fullname, new_fullname)
    repositories.local.rmi(image.fullname)
    # update the store
    images.rename(image.fullname, new_fullname)

def rename(images, repositories: Repositories, requester, image_name, new_name):
    if not validate_image_name(requester, new_name):
        return
    image = images.get_user_unused_image_from_name(requester, image_name)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_name(requester, new_name, expected=False):
            do_rename(images, repositories, image, new_name)
