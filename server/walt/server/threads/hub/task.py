
# This object represents a task that was requested by the client
# and that must be performed by the main thread.
class Task(object):
    def __init__(self, registry, target_api, attr, args, kwargs,
                link_info, result_cb):
        self.registry = registry
        self.desc = attr, tuple(args), tuple(kwargs.items())
        self.link_info = link_info
        self.result_cb = result_cb
        self.exposed_target_api = target_api
        self.exposed_link_info = link_info
        self.async_mode = False
    def exposed_set_async(self):
        self.async_mode = True
    def exposed_is_async(self):
        return self.async_mode
    def exposed_desc(self):
        return self.desc
    def exposed_return_result(self, res):
        if self.result_cb:
            self.result_cb(res)
        self.registry.forget(self)

# This class allows to manage the lifecycle of tasks
# (wrt. garbage collection)
class TaskRegistry(object):
    def __init__(self):
        self.tasks_fifo = []
        self.tasks_running = set()
    def add(self, t):
        self.tasks_fifo.insert(0, t)
    def next(self):
        t = self.tasks_fifo.pop()
        self.tasks_running.add(t)
        return t
    def forget(self, t):
        if t in self.tasks_fifo:
            self.tasks_fifo.remove(t)
        if t in self.tasks_running:
            self.tasks_running.remove(t)
    def print_status(self):
        print 'task registry:'
        print '%d tasks waiting' % len(self.tasks_fifo)
        print '%d tasks running' % len(self.tasks_running)
