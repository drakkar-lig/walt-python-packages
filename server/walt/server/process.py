import itertools
import os
import pdb
import signal
import sys
import traceback
import setproctitle

from collections import defaultdict
from datetime import datetime
from functools import cached_property
from multiprocessing import Pipe, Process, current_process
from os import getpid
from pathlib import Path
from select import select

from walt.common.apilink import AttrCallAggregator, AttrCallRunner
from walt.common.evloop import BreakLoopRequested, EventLoop
from walt.common.tools import AutoCleaner, SimpleContainer, on_sigterm_throw_exception
from walt.common.tools import interrupt_print
from walt.server.tools import set_rlimits

TRACKEXEC_LOG_DIR = Path("/var/log/walt/trackexec")
INVALID_PIPE_ERRORS = (EOFError, ConnectionResetError, BrokenPipeError)


# Notes about signals:
# We manage signals per-process, thus we have to use os.setpgrp()
# to have each subprocess in its own process group.
# SIGHUP is sent by systemd to the deamon process, so the daemon
# process forwards this signal to its subprocess server-main.
# The daemon manages its subprocesses by using subprocess.Process()
# objects, and uses t.join() to wait for their end. The return code
# t.retcode allows to detect if the subprocess failed to end.
# The subprocesses may also run sub-sub-processes, such as a process
# for each virtual node or a temporary process for exploring the
# filesystem of a node or an image. These sub-sub-processes use
# walt.server.popen.BetterPopen class. They call os.setpgrp() too.
# Their parent process automatically calls os.waitpid() when they end,
# an event we detect by catching the SIGCHLD signal.
# Note that the daemon process does not implement this automatic call
# to os.waitpid() because otherwise t.retcode would not be set,
# it would remain "None", which normally means that the subprocess
# is still running. It uses t.join() instead.


def transmit_sighup_to_main(main_pid):
    def signal_handler(sig, frame):
        interrupt_print("SIGHUP received by daemon. Transmitting to main.")
        os.kill(main_pid, sig)

    signal.signal(signal.SIGHUP, signal_handler)


def fix_pdb():
    # Monkey patch pdb for usage in a subprocess.
    # For this, it will call current_process().readline(), which
    # actually requests input lines to the daemon process, which
    # manages the tty input.
    pdb.SavedPdb = pdb.Pdb

    class BetterPdb(pdb.SavedPdb):
        def interaction(self, *args, **kwargs):
            sys_stdin_readline_saved = sys.stdin.readline
            try:
                from multiprocessing import current_process
                self.prompt = f"(Pdb {current_process().name}) "
                sys.stdin.readline = current_process().readline
                pdb.SavedPdb.interaction(self, *args, **kwargs)
            finally:
                sys.stdin.readline = sys_stdin_readline_saved

    pdb.Pdb = BetterPdb


def _instanciate_ev_loop():
    ev_loop = EventLoop()
    if TRACKEXEC_LOG_DIR.exists():
        from walt.server.trackexec import precise_timestamping
        ev_loop.idle_section_hook = precise_timestamping
    return ev_loop


def _update_trackexec_symlink_latest(target_dir):
    symlink_latest = TRACKEXEC_LOG_DIR / "latest"
    try:
        if symlink_latest.readlink() == target_dir:
            # symlink has been created by another concurrent process
            # nothing to do
            return
        else:
            # symlink must be updated, remove it first
            # (set missing_ok=True to deal with concurrent processes)
            symlink_latest.unlink(missing_ok=True)
    except Exception:
        pass  # symlink did not exist, continue below
    try:
        symlink_latest.symlink_to(target_dir)
    except Exception:
        pass  # a concurrent process did it


def _init_trackexec(name, start_time):
    if TRACKEXEC_LOG_DIR.exists():
        import walt
        from walt.server.trackexec import record
        start_time_dir = start_time.strftime("%y%m%d-%H%M%S")
        _update_trackexec_symlink_latest(start_time_dir)
        log_dir_path = TRACKEXEC_LOG_DIR / start_time_dir / name
        record(walt, log_dir_path)


def _log_dbg_exit(line):
    time_label = datetime.now().strftime("%H:%M:%S.%f")[:12]
    print(f"exit: {time_label} {line}")


class EvProcess(Process):
    def __init__(self, manager, name, level):
        Process.__init__(self, name=name)
        self.pipe_process, self.pipe_manager = Pipe()
        manager.attach_file(self, self.pipe_process)
        manager.attach_file(manager, self.pipe_manager)
        manager.register_process(self, level)
        self.start_time = datetime.now()

    def set_startup_files_info(self, files):
        self._startup_files_info = files

    def run(self):
        setproctitle.setproctitle(f"walt-server-daemon:{self.name}")
        # set appropriate OS resource limits
        set_rlimits()
        # each process should be in its own group to avoid receiving
        # signals targetting others
        os.setpgrp()
        # fix pdb when running in a subprocess
        fix_pdb()
        # SIGINT and SIGTERM signals should be sent to the daemon only, not to
        # its subprocesses
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        # SIGHUP will be allowed only when idle in evloop
        signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGHUP])
        # close file descriptors that were opened for other Process objects,
        # and ensure our files are not inheritable by our future subprocesses
        for proc_name, files in self._startup_files_info.items():
            if proc_name == self.name:
                for f in files:
                    os.set_inheritable(f.fileno(), False)
            else:
                for f in files:
                    f.close()
        # run
        self.ev_loop = _instanciate_ev_loop()
        self.ev_loop.register_listener(self)
        try:
            self.prepare()
            # if the admin created directory /var/log/walt/trackexec,
            # enable execution tracking
            _init_trackexec(self.name, self.start_time)
            # run the event loop
            self.ev_loop.loop()
        except BreakLoopRequested:
            return  # end of propagated exit procedure
        except BaseException:
            # we caught the initial exception on this process, display it
            # and start the clean exit procedure
            traceback.print_exc()
            # notify manager it should stop other processes
            self.pipe_process.send("START_EXIT")
            # cleanup
            self.failsafe_cleanup()

    def fileno(self):
        return self.pipe_process.fileno()

    def handle_event(self, ts):
        msg = self.pipe_process.recv()
        assert msg == "PROPAGATED_EXIT", f"Unexpected message in pipe_process: {msg}"
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
        _log_dbg_exit(f"entering cleanup function for {self.name}")
        try:
            self.cleanup()
            _log_dbg_exit("cleanup function has ended")
            # notify we ended
            self.pipe_process.send("END_EXIT")
            # close our files
            for f in self._startup_files_info[self.name]:
                f.close()
        except Exception:
            traceback.print_exc()
        finally:
            # stop trackexec
            if TRACKEXEC_LOG_DIR.exists():
                from walt.server.trackexec import stop
                stop()

    def readline(self):
        self.pipe_process.send("GET_INPUT_LINE")
        return self.pipe_process.recv()


class EvProcessesManager(object):
    def __init__(self):
        self.process_levels = defaultdict(list)
        self.initial_failing_process = None
        self.graceful_exit = True  # by default
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
            t.set_startup_files_info(self.files)
        with AutoCleaner(self):
            # start sub processes
            for t in self.processes:
                t.start()
                if t.name == "server-main":
                    main_pid = t.pid
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
            transmit_sighup_to_main(main_pid)
            # Note: it seems SIGHUP does not interrupt the select()
            while True:
                r, w, e = select(read_set, (), read_set)
                try:
                    msg = r[0].recv()
                    if msg == "START_EXIT":
                        break
                    if msg == "GET_INPUT_LINE":
                        r[0].send(sys.stdin.readline())
                        continue
                    raise Exception("Unexpected message in pipe_manager")
                except Exception as e:
                    print("recv:", e)
                    # the process may have crashed without a possibility to notify
                    # this process manager
                    self.graceful_exit = False
                    break
            for t in self.processes:
                if t.pipe_manager is r[0]:
                    self.initial_failing_process = t
                    if not self.graceful_exit:
                        _log_dbg_exit(f"{t.name} seems to have crashed")
                    else:
                        _log_dbg_exit(f"requested by {t.name}")
                    break

    def cleanup(self):
        # cleanup processes that are still alive
        for level in sorted(self.process_levels.keys(), reverse=True):
            processes = self.process_levels[level]
            for t in processes:
                if t is not self.initial_failing_process:
                    _log_dbg_exit(f"propagating exit to {t.name}")
                    try:
                        t.pipe_manager.send("PROPAGATED_EXIT")
                    except Exception:
                        _log_dbg_exit(f"{t.name} is not responding")
                #_log_dbg_exit(f"waiting for {t.name} process to end")
                has_msg = t.pipe_manager.poll(20)
                if not has_msg:
                    _log_dbg_exit(f"sending SIGTERM to {t.name}")
                    t.terminate()
                    has_msg = t.pipe_manager.poll(5.0)
                clean_exit = False
                try:
                    if has_msg:
                        t.pipe_manager.recv()  # msg is probably "END_EXIT"
                        #_log_dbg_exit(f"{t.name} process did end")
                        clean_exit = True
                finally:
                    if not clean_exit:
                        _log_dbg_exit(f"sending SIGKILL to {t.name}")
                        t.kill()


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

    @property
    def closed(self):
        return self.pipe.closed


PRIORITIES = {"RESULT": 0, "EXCEPTION": 1, "API_CALL": 2}


class RPCService:
    def __init__(self, **service_handlers):
        # avoid call to self.__setattr__
        super().__setattr__("service_handlers", service_handlers)

    def __getattr__(self, service_name):
        handler = self.service_handlers.get(service_name)
        if handler is None:
            raise AttributeError
        else:
            return handler

    def __delattr__(self, service_name):
        del self.service_handlers[service_name]


class RPCSession:
    def __init__(self, connector, remote_req_id, local_service):
        self._connector = connector
        self._args = (remote_req_id, local_service)

    @property
    def do_sync(self):
        return AttrCallAggregator(self._connector.sync_runner, p_args=self._args)

    @property
    def do_async(self):
        return AttrCallAggregator(self._connector.async_runner, p_args=self._args)


class RPCTask(object):
    def __init__(self, connector, remote_req_id, task_label):
        self.connector = connector
        self.remote_req_id = remote_req_id
        self._async_mode = False
        self._completed = False
        self._task_label = task_label

    def set_async(self):
        self._async_mode = True

    def is_async(self):
        return self._async_mode

    def return_result(self, res):
        assert (
            not self._completed
        ), f"{current_process().name} Returning twice from the same task"
        # print('__DEBUG__', repr(self.connector), 'RESULT', self.remote_req_id, res)
        if not self.connector.closed:
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
        if not self.connector.closed:
            self.connector.write(("RESULT", self.remote_req_id, Exception(str(e))))
        self._completed = True

    def is_completed(self):
        return self._completed

    def __repr__(self):
        return f"<RPCTask {self._task_label}>"

    def __del__(self):
        if self.is_async():
            if not self._completed:
                print(f"{self}: garbage collected, but return_result() never called.",
                      file=sys.stderr)


class RPCContext(object):
    def __init__(self, connector, remote_req_id, local_service, task_label):
        self._local_service = local_service
        self.task = RPCTask(connector, remote_req_id, task_label)

    @cached_property
    def remote_service(self):
        return RPCSession(self.task.connector,
                          self.task.remote_req_id,
                          self._local_service)


class RPCProcessConnector(ProcessConnector):
    def __init__(self, local_context=True, label=None, serialize_reqs=False):
        ProcessConnector.__init__(self)
        self.submitted_tasks = {}
        self.ids_generator = None
        self.results = {}
        self.default_service = None
        self.default_session = None
        self.do_async = None
        self.do_sync = None
        self.local_context = local_context
        self.label = label
        self.ev_loop = None
        self._serialize_reqs = serialize_reqs
        self._next_reqs = None

    def __getstate__(self):
        assert self.default_service is None, \
                "cannot pickle RPCProcessConnector after it is configured"
        return self.__dict__

    def __setstate__(self, state):
        self.__dict__ = state

    def configure(self, default_local_service=None):
        self.default_service = AttrCallRunner(default_local_service)
        self.default_session = self.create_session(default_local_service)
        self.do_async = self.default_session.do_async
        self.do_sync = self.default_session.do_sync
        self.ev_loop = current_process().ev_loop

    def __repr__(self):
        if self.label is not None:
            return f"<connector: {self.label}>"
        else:
            return "<connector>"

    def create_session(self, local_service=None):
        return RPCSession(self, -1, local_service)

    def handle_event(self, ts):
        return self.handle_next_event()

    def handle_next_event(self):
        try:
            events = [self.read()]
            while self.poll():
                events.append(self.read())
        except INVALID_PIPE_ERRORS:
            print(f"{repr(self)}: closed on remote end, self-removing from loop.")
            return False
        events.sort(key=lambda x: PRIORITIES[x[0]])
        # print('__DEBUG__', repr(self), 'new events', events)
        for event in events:
            if event[0] == "API_CALL":
                self.handle_api_call(*event[1:])
                continue
            elif event[0] == "RESULT":
                # if we serialize, now that we have a new result check if
                # another request was waiting to be sent
                if self._serialize_reqs:
                    if len(self._next_reqs) > 0:
                        req, self._next_reqs = self._next_reqs[0], self._next_reqs[1:]
                        self._write_task(req)  # write next pending req
                    else:
                        self._next_reqs = None   # no more pending reqs
                # process this new result
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
        s_args = tuple(f"{repr(v)}" for v in args)
        s_kwargs = tuple(f"{k}={repr(v)}" for k, v in kwargs.items())
        proto_args = ", ". join(s_args + s_kwargs)
        task_label = f"{path}({proto_args})"
        context = RPCContext(self, remote_req_id, local_service, task_label)
        if self.local_context:
            args = (context,) + args
        try:
            res = local_service.do(path, args, kwargs)
        except BreakLoopRequested:
            raise
        except BaseException as e:
            try:
                context.task.return_exception(e)
            except INVALID_PIPE_ERRORS:
                print(f"{repr(self)}: closed on remote end, "
                      "could not return exception.")
            return
        if not context.task.is_async():
            try:
                context.task.return_result(res)
            except INVALID_PIPE_ERRORS:
                print(f"{repr(self)}: closed on remote end, "
                      "could not return task result.")

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

        def loop_condition():
            return local_req_id not in self.results

        # check if calling the remote service may involve remote calls
        # back to a local service; if not, limit reentrance code complexity
        # by blocking on this call only.
        opts = {}
        if local_service is None:
            opts.update(single_listener = self)
        self.ev_loop.loop(loop_condition, **opts)
        result = self.results.pop(local_req_id)
        if isinstance(result, Exception):
            print(current_process().name + ": Remote exception returned here.")
            raise result
        else:
            return result

    def send_task(self, remote_req_id, local_service, path, args, kwargs, sync_call):
        if self.ids_generator is None:
            self.ids_generator = itertools.count()
        local_req_id = next(self.ids_generator)
        self.last_req_id = local_req_id
        if local_service is not None:
            local_service = AttrCallRunner(local_service)
        self.submitted_tasks[local_req_id] = SimpleContainer(
            local_service=local_service,
            path=path,
            args=args,
            kwargs=kwargs,
            sync_call=sync_call,
            result_cb=None,
            exception_cb=None,
        )
        # print('__DEBUG__', repr(self),
        #      'API_CALL', remote_req_id, local_req_id, path, args, kwargs)
        req = ("API_CALL", remote_req_id, local_req_id, path, args, kwargs)
        if self._serialize_reqs:
            if self._next_reqs is None:     # no current req
                self._next_reqs = []        # start enqueuing next reqs
                self._write_task(req)       # and send this one
            else:
                self._next_reqs.append(req) # enqueue this req
        else:
            self._write_task(req)
        return local_req_id

    def _write_task(self, req):
        try:
            self.write(req)
        except INVALID_PIPE_ERRORS:
            print(f"{repr(self)}: closed on remote end, could not send task.")


class SyncRPCProcessConnector(RPCProcessConnector):
    def __getattr__(self, attr):
        if self.default_session is not None:
            return getattr(self.default_session.do_sync, attr)
        else:
            raise AttributeError
