import sys, traceback
from walt.common.thread import ThreadConnector

class BlockingTasksManager(ThreadConnector):
    def __init__(self, tasks, *args, **kwargs):
        ThreadConnector.__init__(self, *args, **kwargs)
        self.next_task_id = 0
        self.tasks = tasks

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)

    def do(self, blocking_task):
        task_id = self.next_task_id
        self.next_task_id += 1
        self.tasks[task_id] = blocking_task
        self.pipe.send(task_id)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.pipe.fileno()

    # when the event loop detects an event for us, this
    # means the background process has completed a
    # task.
    def handle_event(self, ts):
        task_id = self.pipe.recv()
        task = self.tasks[task_id]
        if isinstance(task.result, Exception):
            print "Exception occured in the blocking tasks thread. Backtrace:"
            # print back trace
            traceback.print_tb(task.result.info[2])
            # print exception message
            print task.result.info[1]
        task.handle_result(task.result)
        del self.tasks[task_id]

    def cleanup(self):
        self.close()

