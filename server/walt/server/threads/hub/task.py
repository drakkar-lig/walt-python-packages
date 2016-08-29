from walt.common.service import RPyCProxy

# This object represents a task that was requested by the client
# and that must be performed by the main thread.
# we let the main thread access the requester, which is an object
# of the client, but since we are in the middle of 2 RPyC layers
# we have to wrap it as a RPyCProxy object.
class Task(object):
    # the following exceptions may occur if the client disconnects,
    # we should ignore them.
    IGNORED = (ReferenceError, EOFError, AttributeError)

    def __init__(self, cs_or_ns, attr, args, kwargs,
                    requester, remote_ip):
        self.desc = cs_or_ns, attr, args, kwargs
        self.resp_q = requester.queue
        self.exposed_requester = RPyCProxy(requester, ignore_spec = Task.IGNORED)
        self.exposed_remote_ip = remote_ip
    def exposed_desc(self):
        return self.desc
    def exposed_return_result(self, res):
        try:
            self.resp_q.put(res)
        except Task.IGNORED:
            # client not longer exists
            pass

