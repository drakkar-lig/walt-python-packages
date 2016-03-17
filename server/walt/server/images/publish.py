import requests

def perform_publish(requester, auth_conf, docker, image_fullname, **kwargs):
    return docker.push(image_fullname, auth_conf, requester.stdout)

class PublishTask(object):
    def __init__(self, q, requester, **kwargs):
        self.response_q = q
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
        self.response_q.put(res)

# this implements walt image publish
def publish(image_store, requester, q, image_tag, blocking, **kwargs):
    image = image_store.get_user_image_from_tag(requester, image_tag)
    if image == None:
        # issue already reported, just unblock the client
        q.put(False)
    else:
        blocking.do(PublishTask(
            image_fullname = image.fullname,
            requester = requester,
            q = q,
            **kwargs
        ))
