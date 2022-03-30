def search(blocking, requester, task, keyword, tty_mode):
    # the result of the task the hub process submitted to us
    # will not be available right now
    task.set_async()
    if tty_mode is None:
        tty_mode = requester.stdout.isatty()
    blocking.search_image(requester, task.return_result, keyword, tty_mode)
