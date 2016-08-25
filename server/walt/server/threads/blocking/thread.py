import sys
from walt.common.thread import EvThread, ThreadConnector

class BlockingTasksManager(object):
    def __init__(self, tasks, connection_to_main):
        self.tasks = tasks
        self.main = connection_to_main

    # let the event loop know what we are reading on
    def fileno(self):
        return self.main.pipe.fileno()

    # when the event loop detects an event for us, this
    # means we have a new task to perform.
    def handle_event(self, ts):
        task_id = self.main.pipe.recv()
        task = self.tasks[task_id]
        try:
            task.result = task.perform()
        except Exception as e:
            e.info = sys.exc_info()
            task.result = e
        self.main.pipe.send(task_id)

    def close(self):
        pass

    def cleanup(self):
        self.close()

class ServerBlockingThread(EvThread):
    def __init__(self, tman, shared):
        EvThread.__init__(self, tman)
        self.main = ThreadConnector()
        self.manager = BlockingTasksManager(shared.tasks, self.main)

    def prepare(self):
        self.register_listener(self.manager)

