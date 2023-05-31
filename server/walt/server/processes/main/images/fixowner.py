from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from walt.server.processes.main.registry import WalTLocalRegistry

MSG_SAME_USER = """\
Invalid username. According to your walt.conf file, you are '%s'!
"""

MSG_IN_USE = """\
Cannot proceed because some images of %s are in use:
%s
"""

MSG_OVERWRITING = """\
Cannot proceed because the following images of %s would overwrite
those with the same name in your working set:
%s
"""

MSG_NO_SUCH_USER = """\
Connot find any images belonging to a user with name '%s'.
Make sure you typed it correctly.
"""

MSG_CHANGED_OWNER = """\
Image %s now belongs to you.
"""


def fix_owner(images, registry: WalTLocalRegistry, requester, other_user):
    username = requester.get_username()
    if not username:
        return None  # client already disconnected, give up
    if username == other_user:
        requester.stderr.write(MSG_SAME_USER % other_user)
        return
    in_use = set()
    candidates = set()
    for image in images.values():
        if image.user == other_user:
            if image.in_use():
                in_use.add(image.name)
            else:
                candidates.add(image)
    if len(in_use) > 0:
        requester.stderr.write(MSG_IN_USE % (other_user, ", ".join(in_use)))
        return
    problematic = set()
    for image in candidates:
        if images.get_user_image_from_name(requester, image.name, expected=None):
            problematic.add(image.name)
    if len(problematic) > 0:
        requester.stderr.write(MSG_OVERWRITING % (other_user, ", ".join(problematic)))
        return
    if len(candidates) == 0:
        requester.stderr.write(MSG_NO_SUCH_USER % other_user)
        return
    # ok, let's do it
    for image in candidates:
        image.filesystem.close()
        # rename the image
        old_fullname = image.fullname
        new_fullname = username + old_fullname.split("/")[1]
        registry.tag(old_fullname, new_fullname)
        registry.rmi(old_fullname)
        # update the store
        images.rename(old_fullname, new_fullname)
        requester.stdout.write(MSG_CHANGED_OWNER % image.name)
