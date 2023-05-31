import itertools
import signal
import sys
import traceback
from collections import defaultdict
from multiprocessing import Pipe, Process, current_process
from select import select

import setproctitle
from walt.common.apilink import AttrCallAggregator, AttrCallRunner
from walt.common.evloop import BreakLoopRequested, EventLoop
from walt.common.tools import AutoCleaner, SimpleContainer, on_sigterm_throw_exception


class EvProcess(Process):
    def __init__(self, manager, name, level):
        Process.__init__(self, name=name)
        self.pipe_process, self.pipe_manager = Pipe()
        manager.attach_file(self, self.pipe_process)
        manager.attach_file(manager, self.pipe_manager)
        manager.register_process(self, level)
        self.ev_loop = EventLoop()

    def set_auto_close(self, files):
        self._auto_close_files = files

    # mimic an event loop
    def __getattr__(self, attr):
        return getattr(self.ev_loop, attr)

    def run(self):
        setproctitle.setproctitle(f"walt-server-daemon:{self.name}")
        # SIGINT and SIGTERM signals should be sent to the daemon only, not to
        # its subprocesses
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        # close file descriptors that were opened for other Process objects
        for f in self._auto_close_files:
            # print(self.name, 'closing fd not for us:', f)
            f.close()
        # run
        self.ev_loop.register_listener(self)
        try:
            self.prepare()
            self.ev_loop.loop()
        except BreakLoopRequested:
            return  # end of propagated exit procedure
        except BaseException:
            # we caught the initial exception on this process, display it
            # and start the clean exit procedure
            traceback.print_exc()
            self.failsafe_cleanup()
            # notify manager it should stop other processes
            self.pipe_process.send("START_EXIT")

    def fileno(self):
        return self.pipe_process.fileno()

    def handle_event(self, ts):
        msg = self.pipe_process.recv()
        assert msg == "PROPAGATED_EXIT", "Unexpected message in pipe_process"
        self.failsafe_cleanup()
        # we have to interrupt the event loop to exit the process
        raise BreakLoopRequested

    def close(self):
        pass  # prevent a call to base class Process.close() when unregistering from
        # the event loop

    def prepare(self):
        pass  # optionally override in subclass

    def cleanup(self):
        pass  # optionally override in subclass

    def failsafe_cleanup(self):
        print(f"exit: calling cleanup function for {self.name}")
        try:
            self.cleanup()
        except Exception:
            traceback.print_exc()


class EvProcessesManager(object):
    def __init__(self):
        self.process_levels = defaultdict(list)
        self.initial_failing_process = None
        self.files = defaultdict(list)
        self.name = "__manager__"

    def register_process(self, t, level):
        self.process_levels[level].append(t)

    def attach_file(self, process, f):
        self.files[process.name].append(f)

    @property
    def processes(self):
        for l_processes in self.process_levels.values():
            yield from l_processes

    def start(self):
        for t in self.processes:
            files_to_close = []
            for proc_name, files in self.files.items():
                if proc_name != t.name:
                    files_to_close += files
            t.set_auto_close(files_to_close)
        with AutoCleaner(self):
            # start sub processes
            for t in self.processes:
                t.start()
            # close file descriptors of sub processes
            # (no longer needed by this Process manager)
            for proc_name, files in self.files.items():
                if proc_name != self.name:
                    for f in files:
                        # print(self.name, 'closing fd not for us:', f)
                        f.close()
            # wait for ending condition
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
                    t.pipe_manager.send("PROPAGATED_EXIT")
                t.join(20)
                if t.exitcode is None:
                    print(f"exit: sending SIGTERM to {t.name}")
                    t.terminate()
                    t.join(5.0)
                if t.exitcode is None:
                    print(f"exit: sending SIGKILL to {t.name}")
                    t.kill()
                    t.join()


class ProcessConnector:
    def __init__(self):
        # the event loop can process events coming from a process
        # connector in random order.
        self.allow_reordering = True

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


PRIORITIES = {"RESULT": 0, "EXCEPTION": 1, "API_CALL": 2}


class RPCService:
    def __init__(self, **service_handlers):
        # avoid call to self.__setattr__
        super().__setattr__("service_handlers", service_handlers)

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
            self.remote_req_id, self.local_service, path, args, kwargs
        )

    def sync_runner(self, path, args, kwargs):
        return self.connector.sync_runner(
            self.remote_req_id, self.local_service, path, args, kwargs
        )


class RPCTask(object):
    def __init__(self, connector, remote_req_id):
        self.connector = connector
        self.remote_req_id = remote_req_id
        self._async_mode = False
        self._completed = False

    def set_async(self):
        self._async_mode = True

    def is_async(self):
        return self._async_mode

    def return_result(self, res):
        assert (
            not self._completed
        ), f"{current_process().name} Returning twice from the same task"
        # print(current_process().name, 'RESULT', self.remote_req_id, res)
        self.connector.write(("RESULT", self.remote_req_id, res))
        self._completed = True

    def return_exception(self, e, print_exc=True):
        assert (
            not self._completed
        ), f"{current_process().name} Returning twice from the same task"
        if print_exc is True:
            print(
                current_process().name
                + ": Exception occured while performing API request:"
            )
            sys.excepthook(*sys.exc_info())
        self.connector.write(("RESULT", self.remote_req_id, Exception(str(e))))
        self._completed = True


class RPCContext(object):
    def __init__(self, connector, remote_req_id, local_service):
        self.remote_service = RPCSession(connector, remote_req_id, local_service)
        self.task = RPCTask(connector, remote_req_id)


class RPCProcessConnector(ProcessConnector):
    def __init__(self, default_service=None, local_context=True, label=None):
        ProcessConnector.__init__(self)
        self.submitted_tasks = {}
        self.ids_generator = itertools.count()
        self.results = {}
        self.default_service = AttrCallRunner(default_service)
        self.default_session = self.create_session(-1, default_service)
        self.do_async = self.default_session.do_async
        self.do_sync = self.default_session.do_sync
        self.local_context = local_context
        self.label = label

    def __repr__(self):
        if self.label is not None:
            return f"<connector: {self.label}>"
        else:
            return "<connector>"

    def create_session(self, remote_req_id=-1, local_service=None):
        return RPCSession(self, remote_req_id, local_service)

    def handle_event(self, ts):
        return self.handle_next_event()

    def handle_next_event(self):
        try:
            events = [self.read()]
            while self.poll():
                events.append(self.read())
        except EOFError:
            print(f"{repr(self)}: closed on remote end, self-removing from loop.")
            return False
        events.sort(key=lambda x: PRIORITIES[x[0]])
        # print(current_process().name, 'new events', events)
        for event in events:
            if event[0] == "API_CALL":
                self.handle_api_call(*event[1:])
                continue
            elif event[0] == "RESULT":
                local_req_id, result = event[1], event[2]
                sync_call = self.submitted_tasks[local_req_id].sync_call
                if sync_call:  # result (or exception) of sync call
                    self.results[local_req_id] = result
                else:
                    if isinstance(result, Exception):  # exception in async call
                        cb = self.submitted_tasks[local_req_id].exception_cb
                        if cb is not None:
                            cb(result)
                        else:
                            # it does not make sense to throw the exception in this
                            # current context since the call was asynchronous: we would
                            # probably interrupt an unrelated procedure.
                            print(
                                f"{current_process().name}: WARNING: A remote "
                                + "exception in an async call was ignored since no "
                                + "exception callback was defined."
                            )
                    else:  # result of async call
                        cb = self.submitted_tasks[local_req_id].result_cb
                        if cb is not None:
                            cb(result)
                del self.submitted_tasks[local_req_id]
                continue
            raise Exception("Broken communication with remote end.")

    def handle_api_call(self, local_req_id, remote_req_id, path, args, kwargs):
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
        if not context.task.is_async():
            context.task.return_result(res)

    def then(self, cb):  # specify callback
        self.submitted_tasks[self.last_req_id].result_cb = cb

    def on_exception(self, cb):  # specify exception callback
        self.submitted_tasks[self.last_req_id].exception_cb = cb

    def async_runner(self, remote_req_id, local_service, path, args, kwargs):
        self.send_task(remote_req_id, local_service, path, args, kwargs, False)
        # return "self" for "<...>.async.func(<args>).then(<cb>)" notation
        return self

    def sync_runner(self, remote_req_id, local_service, path, args, kwargs):
        local_req_id = self.send_task(
            remote_req_id, local_service, path, args, kwargs, True
        )

        # resume the event loop until we get the expected result
        def loop_condition():
            return local_req_id not in self.results

        current_process().ev_loop.loop(loop_condition)
        result = self.results.pop(local_req_id)
        if isinstance(result, Exception):
            print(current_process().name + ": Remote exception returned here.")
            raise result
        else:
            return result

    def send_task(self, remote_req_id, local_service, path, args, kwargs, sync_call):
        local_req_id = next(self.ids_generator)
        self.last_req_id = local_req_id
        self.submitted_tasks[local_req_id] = SimpleContainer(
            local_service=AttrCallRunner(local_service),
            path=path,
            args=args,
            kwargs=kwargs,
            sync_call=sync_call,
            result_cb=None,
            exception_cb=None,
        )
        # print('__DEBUG__', current_process().name,
        #      'API_CALL', remote_req_id, local_req_id, path, args, kwargs)
        self.write(("API_CALL", remote_req_id, local_req_id, path, args, kwargs))
        return local_req_id


class SyncRPCProcessConnector(RPCProcessConnector):
    def __getattr__(self, attr):
        return getattr(self.default_session.do_sync, attr)

    def is_valid(self):
        return True
