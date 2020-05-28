# this implements walt image squash
def squash(requester, server, image_fullname):
    store = server.images.store
    image = store[image_fullname]
    need_remount = image.in_use
    if need_remount:
        # umount
        store.umount_used_image(image)
    image.squash()
    requester.stdout.write('Image was squashed successfully.\n')
    if need_remount:
        # re-mount
        store.update_image_mounts()
        return 'OK_BUT_REBOOT_NODES'
    return 'OK'
