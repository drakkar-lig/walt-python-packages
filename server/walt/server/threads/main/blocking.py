from walt.common.thread import RPCThreadConnector
from walt.common.apilink import AttrCallRunner, AttrCallAggregator

class BlockingTasksManager(RPCThreadConnector):
    def session(self, requester):
        # we will receive:
        # service.<func>(rpc_context, <args...>)
        # and we must forward the call as:
        # requester.<func>(<args...>)
        # the following code handles this forwarding
        # and removal of the 'rpc_context' parameter.
        runner = AttrCallRunner(requester)
        def forward_to_requester(attr, args, kwargs):
            return runner.do(attr, args[1:], kwargs)
        service = AttrCallAggregator(forward_to_requester)
        return self.local_service(service)

    def clone_image(self, requester, result_cb, *args, **kwargs):
        self.session(requester).async.clone_image(*args, **kwargs).then(result_cb)

    def search_image(self, requester, result_cb, *args, **kwargs):
        self.session(requester).async.search_image(*args, **kwargs).then(result_cb)

    def publish_image(self, requester, result_cb, *args, **kwargs):
        self.session(requester).async.publish_image(*args, **kwargs).then(result_cb)

    def update_hub_metadata(self, requester, result_cb, *args, **kwargs):
        self.session(requester).async.update_hub_metadata(*args, **kwargs).then(result_cb)

    def pull_image(self, image_fullname, result_cb):
        self.async.pull_image(image_fullname).then(result_cb)

    def stream_db_logs(self, logs_handler):
        # request the blocking task to stream db logs
        self.session(logs_handler).async.stream_db_logs(
                            **logs_handler.params)

