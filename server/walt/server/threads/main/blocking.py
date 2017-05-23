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

    def stream_db_logs(self, logs_handler):
        # ensure all past logs are commited
        logs_handler.db.commit()
        # create a server cursor
        cursor = logs_handler.db.get_server_cursor()
        # define callback function
        def cb(res):
            cursor.close()
            logs_handler.notify_history_processed()
        # request the blocking task to stream logs
        self.session(logs_handler).async.stream_db_logs(
                cursor.name, **logs_handler.params).then(cb)

