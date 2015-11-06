from walt.server.images.image import validate_image_tag

def do_rename(images, docker, old_fullname, new_tag):
    name, old_tag = old_fullname.split(':')
    new_fullname = "%s:%s" % (name, new_tag)
    # rename the docker image
    docker.tag(old_fullname, new_fullname)
    docker.rmi(old_fullname)
    # update the store
    images.rename(old_fullname, new_fullname)

def rename(images, docker, requester, image_tag, new_tag):
    if not validate_image_tag(requester, new_tag):
        return
    image = images.get_user_unmounted_image_from_tag(requester, image_tag)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_tag(requester, new_tag, expected=False):
            do_rename(images, docker, image.fullname, new_tag)

