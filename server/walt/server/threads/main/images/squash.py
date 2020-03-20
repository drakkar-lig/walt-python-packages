def squash(store, blocking, requester, task, image_name):
    image = store.get_user_image_from_name(requester, image_name)
    if image == None:
        # issue already reported, return to unblock the client
        return False
    if image.task_label:
        requester.stderr.write('Cannot open image %s because a %s is already running.\n' % \
                                (image_name, image.task_label))
        return None
    image.task_label = 'squash process'
    task.set_async()    # result will be available later
    blocking.squash_image(
                requester,
                task.return_result,
                image_fullname = image.fullname)
