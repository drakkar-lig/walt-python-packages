
def remove(images, docker, requester, image_name):
    image = images.get_user_unmounted_image_from_name(requester, image_name)
    if image:   # otherwise issue is already reported
        docker.local.rmi(image.fullname)
        images.remove(image.fullname)

