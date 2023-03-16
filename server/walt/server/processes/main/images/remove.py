from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from walt.server.processes.main.repository import WalTLocalRepository


def remove(images, repository: WalTLocalRepository, requester, image_name):
    image = images.get_user_unused_image_from_name(requester, image_name)
    if image:   # otherwise issue is already reported
        image.filesystem.close()
        repository.rmi(image.fullname)
        images.remove(image.fullname)
        return True
    else:
        return False
