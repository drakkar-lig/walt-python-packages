from walt.common.thread import EvThread
from walt.server.threads.hub.client import RPyCClientServer
from walt.server.threads.hub.main import MainThreadConnector

class ServerHubThread(EvThread):
    def __init__(self, tman, shared):
        EvThread.__init__(self, tman)
        self.tasks = []
        self.main = MainThreadConnector(self)
        self.rpyc_client_server = RPyCClientServer(self.tasks, self.main)

    def prepare(self):
        self.rpyc_client_server.prepare(self.ev_loop)
        self.register_listener(self.main)
        self.register_listener(self.rpyc_client_server)

