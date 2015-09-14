from walt.server.images.image import validate_image_tag

def do_rename(images, c, old_fullname, new_tag):
    name, old_tag = old_fullname.split(':')
    new_fullname = "%s:%s" % (name, new_tag)
    # rename the docker image
    c.tag(image=old_fullname, repository=name, tag=new_tag)
    c.remove_image(image=old_fullname, force=True)
    # update the store
    images.refresh()

def rename(images, c, requester, image_tag, new_tag):
    if not validate_image_tag(requester, new_tag):
        return
    image = images.get_user_unmounted_image_from_tag(requester, image_tag)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_tag(requester, new_tag, expected=False):
            do_rename(images, c, image.fullname, new_tag)

