from walt.server.images.image import validate_image_tag

def do_copy(images, docker, old_fullname, new_tag):
    name, old_tag = old_fullname.split(':')
    new_fullname = "%s:%s" % (name, new_tag)
    # add a tag to the docker image
    docker.tag(old_fullname, new_fullname)
    # update the store
    images.refresh()

def copy(images, docker, requester, image_tag, new_tag):
    if not validate_image_tag(requester, new_tag):
        return
    image = images.get_user_image_from_tag(requester, image_tag)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_tag(requester, new_tag, expected=False):
            do_copy(images, docker, image.fullname, new_tag)

