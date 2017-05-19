def search(blocking, requester, task, keyword):
    # the result of the task the hub thread submitted to us
    # will not be available right now
    task.set_async()
    blocking.search_image(requester, task.return_result, keyword)
