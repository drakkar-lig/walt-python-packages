def update_walt_software(images, requester, image_tag):
    image = images.get_user_image_from_tag(requester, image_tag)
    if image:   # otherwise issue is already reported
        image.update_walt_software()

