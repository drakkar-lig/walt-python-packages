def squash(store, blocking, requester, task, image_name, confirmed):
    image = store.get_user_image_from_name(requester, image_name)
    if image == None:
        # issue already reported, return to unblock the client
        return 'FAILED'
    if image.task_label:
        requester.stderr.write('Cannot open image %s because a %s is already running.\n' % \
                                (image_name, image.task_label))
        return 'FAILED'
    if not confirmed and store.warn_if_would_reboot_nodes(requester, image_name):
        return 'NEEDS_CONFIRM'
    image.task_label = 'squash process'
    task.set_async()    # result will be available later
    return blocking.squash_image(
                requester,
                task.return_result,
                image_fullname = image.fullname)
