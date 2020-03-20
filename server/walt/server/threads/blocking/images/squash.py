# this implements walt image squash
def squash(requester, server, image_fullname):
    store = server.images.store
    image = store[image_fullname]
    was_mounted = image.mounted
    if was_mounted:
        # umount
        store.umount_used_image(image)
    image.squash()
    if was_mounted:
        # re-mount
        store.update_image_mounts()
    image.task_label = None
