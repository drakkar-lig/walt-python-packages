
MSG_SAME_USER="""\
Invalid username. According to your walt.conf file, you are '%s'!
"""

MSG_MOUNTED="""\
Cannot proceed because some images of %s are mounted:
%s
"""

MSG_OVERWRITING="""\
Cannot proceed because the following images of %s would overwrite
those with the same name in your working set:
%s
"""

MSG_NO_SUCH_USER="""\
Connot find any images belonging to a user with name '%s'.
Make sure you typed it correctly.
"""

MSG_CHANGED_OWNER="""\
Image %s now belongs to you.
"""

def fix_owner(images, docker, requester, other_user):
    if requester.username == other_user:
        requester.stderr.write(MSG_SAME_USER % other_user)
        return
    mounted = set()
    candidates = set()
    for image in images.values():
        if image.user == other_user:
            if image.mounted:
                mounted.add(image.tag)
            else:
                candidates.add(image)
    if len(mounted) > 0:
        requester.stderr.write(MSG_MOUNTED % \
                (other_user, ', '.join(mounted)))
        return
    problematic = set()
    for image in candidates:
        if images.get_user_image_from_tag(requester, image.tag,
                                    expected = None, ready_only = False):
            problematic.add(image.tag)
    if len(problematic) > 0:
        requester.stderr.write(MSG_OVERWRITING % \
                (other_user, ', '.join(problematic)))
        return
    if len(candidates) == 0:
        requester.stderr.write(MSG_NO_SUCH_USER % other_user)
        return
    # ok, let's do it
    for image in candidates:
        # rename the docker image
        old_fullname = image.fullname
        new_fullname = "%s/walt-node:%s" % (requester.username, image.tag)
        docker.tag(old_fullname, new_fullname)
        docker.rmi(old_fullname)
        # update the store
        images.rename(old_fullname, new_fullname)
        requester.stdout.write(MSG_CHANGED_OWNER % image.tag)

