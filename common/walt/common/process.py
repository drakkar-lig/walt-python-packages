import os, sys, signal, itertools, traceback
from collections import defaultdict
from multiprocessing import Pipe, Process, current_process
from select import select
from walt.common.evloop import EventLoop, BreakLoopRequested
from walt.common.tools import AutoCleaner, SimpleContainer
from walt.common.tools import on_sigterm_throw_exception
from walt.common.apilink import AttrCallAggregator, AttrCallRunner

class EvProcess(Process):
    def __init__(self, manager, name, level):
        Process.__init__(self, name = name)
        self.pipe_process, self.pipe_manager = Pipe()
        manager.register_process(self, level)
        self.ev_loop = EventLoop()

    # mimic an event loop
    def __getattr__(self, attr):
        return getattr(self.ev_loop, attr)

    def run(self):
        # SIGINT and SIGTERM signals should be sent to the dameon only, not to its subprocesses
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        # run
        self.ev_loop.register_listener(self)
        try:
            self.prepare()
            self.ev_loop.loop()
        except BreakLoopRequested:
            return  # end of propagated exit procedure
        except BaseException as e:
            # we caught the initial exception on this process, display it
            # and start the clean exit procedure
            traceback.print_exc()
            self.failsafe_cleanup()
            self.pipe_process.send("START_EXIT") # notify manager it should stop other processes

    def fileno(self):
        return self.pipe_process.fileno()

    def handle_event(self, ts):
        msg = self.pipe_process.recv()
        assert msg == "PROPAGATED_EXIT", "Unexpected message in pipe_process"
        self.failsafe_cleanup()
        # we have to interrupt the event loop to exit the process
        raise BreakLoopRequested

    def close(self):
        pass    # prevent a call to base class Process.close() when unregistering from the event loop

    def prepare(self):
        pass    # optionally override in subclass

    def cleanup(self):
        pass    # optionally override in subclass

    def failsafe_cleanup(self):
        print(f'exit: calling cleanup function for {self.name}')
        try:
            self.cleanup()
        except:
            traceback.print_exc()

class EvProcessesManager(object):
    def __init__(self):
        self.process_levels = defaultdict(list)
        self.initial_failing_process = None
    def register_process(self, t, level):
        self.process_levels[level].append(t)
    @property
    def processes(self):
        for l_processes in self.process_levels.values():
            yield from l_processes
    def start(self):
        with AutoCleaner(self):
            for t in self.processes:
                t.start()
            read_set = tuple(t.pipe_manager for t in self.processes)
            on_sigterm_throw_exception()
            r, w, e = select(read_set, (), read_set)
            msg = r[0].recv()
            assert msg == "START_EXIT", "Unexpected message in pipe_manager"
            for t in self.processes:
                if t.pipe_manager is r[0]:
                    self.initial_failing_process = t
                    break
    def cleanup(self):
        # cleanup processes that are still alive
        for level in sorted(self.process_levels.keys(), reverse=True):
            processes = self.process_levels[level]
            for t in processes:
                if t is not self.initial_failing_process:
                    t.pipe_manager.send('PROPAGATED_EXIT')
                t.join(20)
                if t.exitcode is None:
                    print(f'exit: sending SIGTERM to {t.name}')
                    t.terminate()
                    t.join(5.0)
                if t.exitcode is None:
                    print(f'exit: sending SIGKILL to {t.name}')
                    t.kill()
                    t.join()

class ProcessConnector:
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

PRIORITIES = { 'RESULT':0, 'EXCEPTION':1, 'API_CALL':2 }

class RPCService:
    def __init__(self, **service_handlers):
        # avoid call to self.__setattr__
        super().__setattr__('service_handlers', service_handlers)
    def __getattr__(self, service_name):
        return self.service_handlers[service_name]
    def __setattr__(self, service_name, service_handler):
        self.service_handlers[service_name] = service_handler
    def __delattr__(self, service_name):
        del self.service_handlers[service_name]

class RPCSession(object):
    def __init__(self, connector, remote_req_id, local_service):
        self.connector = connector
        self.do_async = AttrCallAggregator(self.async_runner)
        self.do_sync = AttrCallAggregator(self.sync_runner)
        self.remote_req_id = remote_req_id
        if local_service is None:
            local_service = RPCService()
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
        #print current_process().name, 'RESULT', self.remote_req_id, res
        self.connector.write(('RESULT', self.remote_req_id, res))
    def return_exception(self, e):
        print(current_process().name + ': Exception occured while performing API request:')
        sys.excepthook(*sys.exc_info())
        self.connector.write(('RESULT', self.remote_req_id, Exception(str(e))))

class RPCContext(object):
    def __init__(self, connector, remote_req_id, local_service):
        self.remote_service = RPCSession(connector, remote_req_id, local_service)
        self.task = RPCTask(connector, remote_req_id)

class RPCProcessConnector(ProcessConnector):
    def __init__(self, default_service = None, local_context = True):
        self.submitted_tasks = {}
        self.ids_generator = itertools.count()
        self.results = {}
        self.default_service = AttrCallRunner(default_service)
        self.default_session = self.create_session(-1, default_service)
        self.do_async = self.default_session.do_async
        self.do_sync = self.default_session.do_sync
        self.local_context = local_context
    def create_session(self, remote_req_id = -1, local_service = None):
        return RPCSession(self, remote_req_id, local_service)
    def handle_event(self, ts):
        return self.handle_next_event()
    def handle_next_event(self):
        events = [ self.read() ]
        while self.poll():
            events.append(self.read())
        events.sort(key=lambda x: PRIORITIES[x[0]])
        for event in events:
            if event[0] == 'API_CALL':
                self.handle_api_call(*event[1:])
                continue
            elif event[0] == 'RESULT':
                local_req_id, result = event[1], event[2]
                if isinstance(result, Exception):
                    print(current_process().name + ': Remote exception returned here.')
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
        if self.local_context:
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
        # resume an event loop process until we get the expected result
        # however, we restrict the event loop to listen only on this channel
        # (otherwise with imbricated sync_runner() calls on different objects
        # avoiding infinite loops would get very complex)
        loop_condition = lambda : (local_req_id not in self.results)
        mini_ev_loop = EventLoop()
        mini_ev_loop.register_listener(self)
        mini_ev_loop.register_listener(current_process())   # also listen for process manager requests
        mini_ev_loop.loop(loop_condition)
        return self.results.pop(local_req_id)
    def send_task(self, remote_req_id, local_service, path, args, kwargs, sync):
        local_req_id = next(self.ids_generator)
        self.last_req_id = local_req_id
        self.submitted_tasks[local_req_id] = SimpleContainer(
                    local_service = AttrCallRunner(local_service),
                    path = path,
                    args = args,
                    kwargs = kwargs,
                    sync = sync,
                    result_cb = None)
        #print current_process().name, 'API_CALL', remote_req_id, local_req_id, path, args, kwargs, sync
        self.write(('API_CALL', remote_req_id, local_req_id, path, args, kwargs, sync))
        return local_req_id

class SyncRPCProcessConnector(RPCProcessConnector):
    def __getattr__(self, attr):
        return getattr(self.default_session.do_sync, attr)
    def is_valid(self):
        return True
