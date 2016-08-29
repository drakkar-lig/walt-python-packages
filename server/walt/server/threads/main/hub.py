from walt.server.threads.main.api.cs import CSAPI
from walt.server.threads.main.api.ns import NSAPI
from walt.common.thread import ThreadConnector

class HubThreadConnector(ThreadConnector):
    def __init__(self, server, *args, **kwargs):
        ThreadConnector.__init__(self, *args, **kwargs)
        images, devices, nodes, logs = \
            server.images, server.devices, server.nodes, server.logs
        self.cs = CSAPI(server, images, devices, nodes, logs)
        self.ns = NSAPI(devices, nodes)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.pipe.fileno()

    # when the event loop detects an event for us, this
    # means the hub thread has a new task for us.
    def handle_event(self, ts):
        self.pipe.recv()
        # pop next task saved by hub thread
        t = self.rpyc.root.pop_task()
        # get task info
        cs_or_ns, attr, args, kwargs = t.desc()
        # lookup task
        api = getattr(self, cs_or_ns)
        m = getattr(api, attr)
        # update requester info
        api.requester = t.requester
        api.remote_ip = t.remote_ip
        # run task
        res = m(*list(args), **dict(kwargs))
        # return result
        t.return_result(res)

    def cleanup(self):
        self.close()

