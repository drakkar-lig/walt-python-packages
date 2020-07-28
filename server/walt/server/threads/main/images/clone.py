from walt.server.threads.main.images.image import validate_image_name

def clone(blocking, server, requester, task, image_name, **kwargs):
    if image_name is not None:
        if not validate_image_name(requester, image_name):
            return  # issue already reported
    # the result of the task the hub thread submitted to us
    # will not be available right now
    task.set_async()
    def callback(clone_result):
        status = clone_result[0]
        if status in ('OK', 'FAILED'):
            task.return_result(status)
        elif status == 'OK_BUT_REBOOT_NODES':
            requester.set_default_busy_label()
            image_fullname = clone_result[1]
            server.reboot_nodes_after_image_change(requester, task.return_result, image_fullname)
    blocking.clone_image(requester, callback, image_name = image_name, **kwargs)
