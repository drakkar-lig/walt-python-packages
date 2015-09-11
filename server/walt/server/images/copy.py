
def do_copy(images, c, old_fullname, new_tag):
    name, old_tag = old_fullname.split(':')
    new_fullname = "%s:%s" % (name, new_tag)
    # add a tag to the docker image
    c.tag(image=old_fullname, repository=name, tag=new_tag)
    # update the store
    images.refresh()

def copy(images, c, requester, image_tag, new_tag):
    image = images.get_user_image_from_tag(requester, image_tag)
    if image:   # otherwise issue is already reported
        if not images.get_user_image_from_tag(requester, new_tag, expected=False):
            do_copy(images, c, image.fullname, new_tag)

