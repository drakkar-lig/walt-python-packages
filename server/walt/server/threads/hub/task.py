
# This object represents a task that was requested by the client
# and that must be performed by the main thread.
class Task(object):
    # the following exceptions may occur if the client disconnects,
    # we should ignore them.
    IGNORED = (ReferenceError, EOFError, AttributeError)

    def __init__(self, target_api, attr, args, kwargs, link_info):
        self.desc = attr, tuple(args), tuple(kwargs.items())
        self.link_info = link_info
        self.exposed_target_api = target_api
        self.exposed_link_info = link_info
    def exposed_desc(self):
        return self.desc
    def exposed_return_result(self, res):
        raise NotImplementedError

class ClientTask(Task):
    def exposed_return_result(self, res):
        try:
            self.link_info.requester.queue.put(res)
        except Task.IGNORED:
            # client not longer exists
            pass

class HubTask(Task):
    def exposed_return_result(self, res):
        pass    # nothing to do

