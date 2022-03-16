from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from walt.server.threads.main.repositories import Repositories


def remove(images, repositories: Repositories, requester, image_name):
    image = images.get_user_unused_image_from_name(requester, image_name)
    if image:   # otherwise issue is already reported
        image.filesystem.close()
        repositories.local.rmi(image.fullname)
        images.remove(image.fullname)
