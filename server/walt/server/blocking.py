import sys, traceback
from multiprocessing import Pipe
from threading import Thread
STOP = -1

class BlockingTasksThread(Thread):
    def __init__(self, tasks, pipe_in, pipe_out):
        Thread.__init__(self)
        self.tasks = tasks
        self.pipe_in = pipe_in
        self.pipe_out = pipe_out

    def run(self):
        while True:
            msg = self.pipe_in.recv()
            if msg == STOP:
                break
            task_id = msg
            task = self.tasks[task_id]
            try:
                task.result = task.perform()
            except Exception as e:
                e.info = sys.exc_info()
                task.result = e
            self.pipe_out.send(task_id)
        self.pipe_in.close()
        self.pipe_out.close()

class BlockingTasksManager(object):
    def __init__(self):
        self.next_task_id = 0
        self.tasks = {}
        self.pipe_requests, pipe_requests_child = Pipe()
        self.pipe_done, pipe_done_child = Pipe()
        self.thread = BlockingTasksThread(
                    self.tasks, pipe_requests_child, pipe_done_child)
        self.thread.start()

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)

    def do(self, blocking_task):
        task_id = self.next_task_id
        self.next_task_id += 1
        self.tasks[task_id] = blocking_task
        self.pipe_requests.send(task_id)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.pipe_done.fileno()

    # when the event loop detects an event for us, this
    # means the background process has completed a
    # task.
    def handle_event(self, ts):
        task_id = self.pipe_done.recv()
        task = self.tasks[task_id]
        if isinstance(task.result, Exception):
            print "Exception occured in the blocking tasks thread. Backtrace:"
            # print back trace
            traceback.print_tb(task.result.info[2])
            # print exception message
            print task.result.info[1]
        task.handle_result(task.result)
        del self.tasks[task_id]

    def close(self):
        self.pipe_requests.send(STOP)
        self.thread.join()
        self.pipe_requests.close()
        self.pipe_done.close()

    def cleanup(self):
        self.close()

