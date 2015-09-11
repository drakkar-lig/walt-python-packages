
def remove(images, c, requester, image_tag):
    image = images.get_user_unmounted_image_from_tag(requester, image_tag)
    if image:   # otherwise issue is already reported
        c.remove_image(
                image=image.fullname, force=True)
        images.refresh()

