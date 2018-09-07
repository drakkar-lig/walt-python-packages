from walt.server.threads.main.images.image import validate_image_name, format_image_fullname

def do_duplicate(images, docker, image, new_name):
    new_fullname = format_image_fullname(image.user, new_name)
    # add a tag to the docker image
    docker.local.tag(image.fullname, new_fullname)
    # update the store
    images.register_image(new_fullname, True)

def duplicate(images, docker, requester, image_name, new_name):
    if not validate_image_name(requester, new_name):
        return
    image = images.get_user_image_from_name(requester, image_name)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_name(requester, new_name, expected=False):
            do_duplicate(images, docker, image, new_name)

