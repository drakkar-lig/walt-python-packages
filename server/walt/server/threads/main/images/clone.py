def clone(blocking, requester, task, **kwargs):
    # the result of the task the hub thread submitted to us
    # will not be available right now
    task.set_async()
    blocking.clone_image(requester, task.return_result, **kwargs)
