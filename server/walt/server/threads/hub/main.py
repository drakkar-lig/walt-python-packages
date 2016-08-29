from walt.common.thread import ThreadConnector
from walt.common.service import RPyCService

@RPyCService
class RPyCMainService(object):
    last_task = None
    def __init__(self, thread):
        self.tasks = thread.tasks
    def exposed_pop_task(self):
        t = self.tasks.pop()
        # avoid garbage collection for now
        RPyCMainService.last_task = t
        return t

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

