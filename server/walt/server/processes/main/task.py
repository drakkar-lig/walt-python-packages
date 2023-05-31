import sys

# This object represents a task that was requested by the hub
# and that must be performed by the main process.


class APISessionTask(object):
    def __init__(self, rpc_context, api_session, attr, args, kwargs):
        self.api_session = api_session
        self.attr = attr
        self.args = args
        self.kwargs = kwargs
        self.rpc_context = rpc_context
        self.context = api_session.context.copy().update(
            task=self, requester=rpc_context.remote_service.do_sync.requester
        )

    def set_async(self):
        self.rpc_context.task.set_async()

    def is_async(self):
        return self.rpc_context.task.is_async()

    def return_result(self, res):
        self.rpc_context.task.return_result(res)

    def run(self):
        try:
            # lookup task
            m = getattr(self.api_session, self.attr)
            # run task
            res = m(self.context, *self.args, **self.kwargs)
        except BaseException as e:
            print("Exception occured while performing API request:")
            sys.excepthook(*sys.exc_info())
            res = e
        # return result, unless async mode was set
        if not self.is_async():
            return res

    def is_alive(self):
        # note: if the requester is disconnected, is_alive() actually returns None.
        return self.context.requester.is_alive() is True
