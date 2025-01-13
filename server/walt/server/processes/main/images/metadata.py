import functools
from walt.server.processes.main.images.tools import handle_missing_credentials


def update_hub_metadata(blocking, requester, task, waltplatform_user, **kwargs):
    if waltplatform_user:
        user = "waltplatform"
    else:
        requester.prompt_missing_registry_credentials("hub")
        user = requester.get_registry_username("hub")
        if not user:
            return None  # client already disconnected, give up
    task.set_async()  # result will be available later
    def callback(result):
        task.return_result(result[0] == 'OK')
    blocking_func = functools.partial(
            blocking.update_hub_metadata,
            requester, user=user, **kwargs)
    handle_missing_credentials(requester, blocking_func, callback)
