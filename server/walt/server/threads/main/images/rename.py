from walt.server.threads.main.images.image import validate_image_name, format_image_fullname

def do_rename(images, docker, image, new_name):
    new_fullname = format_image_fullname(image.user, new_name)
    # rename the docker image
    docker.local.tag(image.fullname, new_fullname)
    docker.local.rmi(image.fullname)
    # update the store
    images.rename(image.fullname, new_fullname)

def rename(images, docker, requester, image_name, new_name):
    if not validate_image_name(requester, new_name):
        return
    image = images.get_user_unmounted_image_from_name(requester, image_name)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_name(requester, new_name, expected=False):
            do_rename(images, docker, image, new_name)

