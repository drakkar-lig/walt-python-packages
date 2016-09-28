from walt.server.threads.main.apisession import APISession
from walt.common.thread import ThreadConnector
from walt.server.threads.main.api.cs import CSAPI
from walt.server.threads.main.api.ns import NSAPI
from walt.server.threads.main.api.ss import SSAPI

class HubThreadConnector(ThreadConnector):
    def __init__(self, server, *args, **kwargs):
        ThreadConnector.__init__(self, *args, **kwargs)
        self.server = server
        self.rpyc_sessions = {}

    # let the event loop know what we are reading on
    def fileno(self):
        return self.pipe.fileno()

    # when the event loop detects an event for us, this
    # means the hub thread has a new task for us.
    def handle_event(self, ts):
        self.pipe.recv()
        # pop next task saved by hub thread
        t = self.rpyc.root.pop_task()
        # retrieve or create associated session
        session = APISession.get(self.server, t)
        # run task
        session.run(t)

    def cleanup(self):
        self.close()

APISession.register_target_api('NSAPI', NSAPI)
APISession.register_target_api('CSAPI', CSAPI)
APISession.register_target_api('SSAPI', SSAPI)

