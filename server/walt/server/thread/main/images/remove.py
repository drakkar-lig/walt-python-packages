
def remove(images, docker, requester, image_tag):
    image = images.get_user_unmounted_image_from_tag(requester, image_tag)
    if image:   # otherwise issue is already reported
        docker.rmi(image.fullname)
        images.remove(image.fullname)

