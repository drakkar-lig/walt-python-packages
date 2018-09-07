from walt.common.thread import EvThread, RPCThreadConnector
from walt.server.threads.blocking.images.clone import clone
from walt.server.threads.blocking.images.publish import publish
from walt.server.threads.blocking.images.metadata import update_hub_metadata
from walt.server.threads.blocking.images.search import search
from walt.server.threads.blocking.logs import stream_db_logs

class BlockingTasksService(object):
    def __init__(self, server):
        self.server = server

    def clone_image(self, context, *args, **kwargs):
        res = clone(context.requester.sync, self.server, *args, **kwargs)
        context.task.return_result(res)

    def search_image(self, context, *args, **kwargs):
        res = search(context.requester.sync, self.server, *args, **kwargs)
        context.task.return_result(res)

    def publish_image(self, context, *args, **kwargs):
        res = publish(context.requester.sync, self.server, *args, **kwargs)
        context.task.return_result(res)

    def update_hub_metadata(self, context, *args, **kwargs):
        res = update_hub_metadata(context.requester.sync, self.server, *args, **kwargs)
        context.task.return_result(res)

    def stream_db_logs(self, context, **params):
        res = stream_db_logs(self.server.db, context.requester.sync, **params)
        context.task.return_result(res)

    def pull_image(self, context, image_fullname):
        res = self.server.docker.hub.pull(image_fullname)
        context.task.return_result(res)

class ServerBlockingThread(EvThread):
    def __init__(self, tman, server):
        EvThread.__init__(self, tman, 'server-blocking')
        service = BlockingTasksService(server)
        self.main = RPCThreadConnector(service)

    def prepare(self):
        self.register_listener(self.main)

