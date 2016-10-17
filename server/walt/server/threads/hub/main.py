from walt.common.thread import ThreadConnector
from walt.common.apilink import APIService

@APIService
class RPyCMainService(object):
    last_task = None
    def __init__(self, thread):
        self.tasks = thread.tasks
    def exposed_pop_task(self):
        return self.tasks.next()

class MainThreadConnector(ThreadConnector):
    def __init__(self, thread):
        self.thread = thread
        service = RPyCMainService(thread)
        ThreadConnector.__init__(self, service)

    def fileno(self):
        return self.rpyc.fileno()

    def handle_event(self, ts):
        self.rpyc.serve()

    def cleanup(self):
        self.close()

