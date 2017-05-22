import sys, signal, itertools
from multiprocessing import Pipe
from threading import Thread, current_thread
from select import select
from walt.common.evloop import EventLoop
from walt.common.tools import AutoCleaner, SimpleContainer
from walt.common.apilink import AttrCallAggregator, AttrCallRunner

class DownwardPropagatedException(Exception):
    pass

class EvThread(Thread):
    def __init__(self, manager, name):
        Thread.__init__(self, name = name)
        self.ev_loop = EventLoop()
        self.pipe_in, self.pipe_out = Pipe()
        self.ev_loop.register_listener(self)
        manager.register_thread(self)

    # mimic an event loop
    def __getattr__(self, attr):
        return getattr(self.ev_loop, attr)

    def run(self):
        try:
            with AutoCleaner(self):
                self.prepare()
                self.ev_loop.loop()
        except DownwardPropagatedException:
            print self.name + ' stopped because of propagated exception.'
        except BaseException as e:
            try:
                self.pipe_in.send(e) # propagate upward
            except BaseException as issue:
                self.pipe_in.send(Exception(str(e)))
            raise

    def fileno(self):
        return self.pipe_in.fileno()

    def forward_exception(self, e):
        self.pipe_out.send(e)

    def handle_event(self, ts):
        self.down_exception = self.pipe_in.recv()
        raise DownwardPropagatedException

    def prepare(self):
        pass    # optionally override in subclass

    def cleanup(self):
        pass    # optionally override in subclass

class EvThreadsManager(object):
    def __init__(self):
        self.threads = []
    def register_thread(self, t):
        self.threads.append(t)
    def start(self):
        try:
            for t in self.threads:
                t.start()
            read_set = tuple(t.pipe_out for t in self.threads)
            r, w, e = select(read_set, (), read_set)
            e = r[0].recv()
            raise e
        except BaseException as e:
            # propagate downward to threads that are still alive
            for t in self.threads:
                try:
                    t.forward_exception(e)
                except:
                    pass

WAIT_MAX = 0.1

class ThreadConnector:
    def connect(self, remote):
        self.pipe, remote.pipe = Pipe()
    def close(self):
        self.pipe.close()
    def fileno(self):
        return self.pipe.fileno()
    def write(self, obj):
        self.pipe.send(obj)
    def read(self):
        return self.pipe.recv()
    def poll(self):
        return self.pipe.poll()
    def wait_next_event(self):
        # we implement a loop in order to make this wait
        # interruptible (every WAIT_MAX seconds)
        while not self.pipe.poll(WAIT_MAX):
            pass

PRIORITIES = { 'RESULT':0, 'EXCEPTION':1, 'API_CALL':2 }

class RPCSession(object):
    def __init__(self, connector, remote_req_id, local_service):
        self.connector = connector
        self.async = AttrCallAggregator(self.async_runner)
        self.sync = AttrCallAggregator(self.sync_runner)
        self.remote_req_id = remote_req_id
        self.local_service = local_service
    def async_runner(self, path, args, kwargs):
        return self.connector.async_runner(
                self.remote_req_id, self.local_service, path, args, kwargs)
    def sync_runner(self, path, args, kwargs):
        return self.connector.sync_runner(
                self.remote_req_id, self.local_service, path, args, kwargs)

class RPCTask(object):
    def __init__(self, connector, remote_req_id):
        self.connector = connector
        self.remote_req_id = remote_req_id
    def return_result(self, res):
        #print current_thread().name, 'RESULT', self.remote_req_id, res
        self.connector.write(('RESULT', self.remote_req_id, res))
    def return_exception(self, e):
        print current_thread().name + ': Exception occured while performing API request:'
        sys.excepthook(*sys.exc_info())
        self.connector.write(('RESULT', self.remote_req_id, Exception(str(e))))

class RPCContext(object):
    def __init__(self, connector, remote_req_id, local_service):
        self.requester = RPCSession(connector, remote_req_id, local_service)
        self.task = RPCTask(connector, remote_req_id)

class RPCThreadConnector(ThreadConnector):
    def __init__(self, default_service = None):
        self.submitted_tasks = {}
        self.ids_generator = itertools.count()
        self.results = {}
        self.default_service = AttrCallRunner(default_service)
        self.default_session = self.create_session(-1, default_service)
        self.async = self.default_session.async
        self.sync = self.default_session.sync
    def local_service(self, local_service):
        return self.create_session(-1, local_service)
    def create_session(self, remote_req_id, local_service):
        return RPCSession(self, remote_req_id, local_service)
    def handle_event(self, ts):
        return self.handle_next_event()
    def handle_next_event(self):
        events = []
        while self.poll():
            events.append(self.read())
        if len(events) == 0:
            return False    # no data, quit
        events.sort(key=lambda x: PRIORITIES[x[0]])
        for event in events:
            if event[0] == 'API_CALL':
                self.handle_api_call(*event[1:])
                continue
            elif event[0] == 'RESULT':
                local_req_id, result = event[1], event[2]
                sync = self.submitted_tasks[local_req_id].sync
                cb = self.submitted_tasks[local_req_id].result_cb
                if cb != None:
                    cb(result)
                if sync:
                    self.results[local_req_id] = result
                del self.submitted_tasks[local_req_id]
                continue
            raise Exception('Broken communication with remote end.')
    def handle_api_call(self, local_req_id, remote_req_id, path, args, kwargs, sync):
        if local_req_id == -1:
            local_service = self.default_service
        else:
            local_service = self.submitted_tasks[local_req_id].local_service
        context = RPCContext(self, remote_req_id, local_service)
        args = (context,) + args
        try:
            res = local_service.do(path, args, kwargs)
        except BaseException as e:
            context.task.return_exception(e)
            return
        if sync:
            context.task.return_result(res)
    def then(self, cb): # specify callback
        self.submitted_tasks[self.last_req_id].result_cb = cb
    def async_runner(self, remote_req_id, local_service, path, args, kwargs):
        local_req_id = self.send_task(remote_req_id, local_service, path, args, kwargs, False)
        return self
    def sync_runner(self, remote_req_id, local_service, path, args, kwargs):
        local_req_id = self.send_task(remote_req_id, local_service, path, args, kwargs, True)
        while not local_req_id in self.results:
            self.wait_next_event()
            status = self.handle_next_event()
            if status == False:
                return None
        return self.results.pop(local_req_id)
    def send_task(self, remote_req_id, local_service, path, args, kwargs, sync):
        local_req_id = self.ids_generator.next()
        self.last_req_id = local_req_id
        self.submitted_tasks[local_req_id] = SimpleContainer(
                    local_service = AttrCallRunner(local_service),
                    path = path,
                    args = args,
                    kwargs = kwargs,
                    sync = sync,
                    result_cb = None)
        #print current_thread().name, 'API_CALL', remote_req_id, local_req_id, path, args, kwargs, sync
        self.write(('API_CALL', remote_req_id, local_req_id, path, args, kwargs, sync))
        return local_req_id
