import requests

def perform_publish(requester, dh_peer, auth_conf, docker, image_fullname, **kwargs):
    return docker.push(image_fullname, dh_peer, auth_conf, requester)

class PublishTask(object):
    def __init__(self, hub_task, requester, **kwargs):
        self.hub_task = hub_task
        self.requester = requester
        self.kwargs = kwargs
    def perform(self):
        return perform_publish(  requester = self.requester,
                        **self.kwargs)
    def handle_result(self, res):
        if isinstance(res, requests.exceptions.RequestException):
            self.requester.stderr.write(
                'Network connection to docker hub failed.\n')
            res = None
        elif isinstance(res, Exception):
            raise res   # unexpected
        self.hub_task.return_result(res)

# this implements walt image publish
def publish(image_store, requester, task, image_tag, blocking, **kwargs):
    image = image_store.get_user_image_from_tag(requester, image_tag)
    if image == None:
        # issue already reported, just unblock the client
        task.return_result(False)
    else:
        task.set_async()    # result will be available later
        blocking.do(PublishTask(
            image_fullname = image.fullname,
            requester = requester,
            hub_task = task,
            **kwargs
        ))
