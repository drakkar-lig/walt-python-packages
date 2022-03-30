def publish(store, blocking, requester, task, image_name, **kwargs):
    image = store.get_user_image_from_name(requester, image_name)
    if image == None:
        # issue already reported, return to unblock the client
        return False
    else:
        task.set_async()    # result will be available later
        blocking.publish_image(
                    requester,
                    task.return_result,
                    image_fullname = image.fullname,
                    **kwargs)
