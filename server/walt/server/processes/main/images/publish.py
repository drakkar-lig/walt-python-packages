import functools
from walt.server.processes.main.images.tools import handle_missing_credentials


def publish(store, blocking, requester, task, image_name, **kwargs):
    image = store.get_user_image_from_name(requester, image_name)
    if image is None:
        # issue already reported, return to unblock the client
        return (False,)
    else:
        task.set_async()  # result will be available later
        def cb(result):
            if result[0] == 'OK':
                task.return_result((True, result[1]))  # result[1] is clone_url
            else:
                task.return_result((False,))  # issue already reported
        blocking_func = functools.partial(
                blocking.publish_image,
                requester, image_fullname=image.fullname, **kwargs)
        handle_missing_credentials(requester, blocking_func, cb)
