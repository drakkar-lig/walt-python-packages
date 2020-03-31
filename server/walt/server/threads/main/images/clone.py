from walt.server.threads.main.images.image import validate_image_name

def clone(blocking, requester, task, image_name, **kwargs):
    if image_name is not None:
        if not validate_image_name(requester, image_name):
            return  # issue already reported
    # the result of the task the hub thread submitted to us
    # will not be available right now
    task.set_async()
    blocking.clone_image(requester, task.return_result, image_name = image_name, **kwargs)
