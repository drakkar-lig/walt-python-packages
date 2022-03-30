def squash(store, blocking, requester, task_callback, image_name, confirmed):
    image = store.get_user_image_from_name(requester, image_name)
    if image == None:
        # issue already reported, return to unblock the client
        task_callback('FAILED')
        return
    if image.task_label:
        requester.stderr.write('Cannot open image %s because a %s is already running.\n' % \
                                (image_name, image.task_label))
        task_callback('FAILED')
        return
    if not confirmed and store.warn_if_would_reboot_nodes(requester, image_name):
        task_callback('NEEDS_CONFIRM')
        return
    image.task_label = 'squash process'
    def task_callback_2(res):
        image.task_label = None
        task_callback(res)
    return blocking.squash_image(
                requester,
                task_callback_2,
                image_fullname = image.fullname)
