import functools
from walt.server.processes.main.images.tools import handle_missing_credentials


def search(blocking, requester, task, keyword, tty_mode):
    # the result of the task the hub process submitted to us
    # will not be available right now
    task.set_async()
    if tty_mode is None:
        tty_mode = requester.stdout.isatty()
    def callback(result):
        task.return_result(result[0] == 'OK')
    blocking_func = functools.partial(
            blocking.search_image,
            requester, keyword=keyword, tty_mode=tty_mode)
    handle_missing_credentials(requester, blocking_func, callback)
