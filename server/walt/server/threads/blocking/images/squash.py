# this implements walt image squash
def squash(requester, server, image_fullname):
    store = server.images.store
    image = store[image_fullname]
    in_use = image.in_use
    image.squash()
    requester.stdout.write('Image was squashed successfully.\n')
    if in_use:
        store.update_image_mounts()
        return 'OK_BUT_REBOOT_NODES'
    return 'OK'
