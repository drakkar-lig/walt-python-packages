
def update_hub_metadata(blocking, requester, task, waltplatform_user, **kwargs):
    if waltplatform_user:
        user = 'waltplatform'
    else:
        user = requester.get_username()
        if not user:
            return None     # client already disconnected, give up
    task.set_async()    # result will be available later
    blocking.update_hub_metadata(
                requester,
                task.return_result,
                user = user,
                **kwargs)
