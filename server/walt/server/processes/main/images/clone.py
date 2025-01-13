import functools
from walt.common.tools import parse_image_fullname
from walt.server.processes.main.images.tools import handle_missing_credentials
from walt.server.processes.main.images.image import validate_image_name


def clone(blocking, server, requester, task, image_name, **kwargs):
    if image_name is not None:
        if not validate_image_name(requester, image_name):
            return {"status": "FAILED"}  # issue already reported
    # the result of the task the hub process submitted to us
    # will not be available right now
    task.set_async()

    def callback(clone_result):
        status = clone_result[0]
        if status == "FAILED":
            task.return_result({"status": "FAILED"})
            return
        image_fullname = clone_result[1]
        fullname, user, image_name = parse_image_fullname(image_fullname)
        if status == "OK":
            task.return_result({"status": "OK", "image_name": image_name})
            return
        if status == "OK_BUT_REBOOT_NODES":

            def return_full_result(status):
                if status == "FAILED":
                    task.return_result({"status": "FAILED"})
                else:
                    task.return_result({"status": "OK", "image_name": image_name})

            requester.set_default_busy_label()
            server.reboot_nodes_after_image_change(
                requester, return_full_result, image_fullname
            )

    blocking_func = functools.partial(
            blocking.clone_image,
            requester, image_name=image_name, **kwargs)
    handle_missing_credentials(requester, blocking_func, callback)
