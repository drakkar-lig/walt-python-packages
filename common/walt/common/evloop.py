#!/usr/bin/env python
import contextlib
import functools
import os
import shlex
import signal
from heapq import heappop, heappush
from multiprocessing import current_process  # noqa: F401
from select import POLLIN, POLLOUT, POLLPRI, poll, select
from subprocess import PIPE, Popen, DEVNULL
from time import time
from collections import defaultdict
from weakref import WeakKeyDictionary


class BreakLoopRequested(Exception):
    pass


POLL_OPS_READ = POLLIN | POLLPRI
POLL_OPS_WRITE = POLLOUT


def is_event_ok(ev):
    # check that there is something to read or write
    return ev & (POLL_OPS_READ | POLL_OPS_WRITE) > 0


# ---------------------------------------------------------------------------
# Ownership of the file descriptors watched by the event loop.
#
# The event loop is the *only* component allowed to close the file objects it
# watches.  To guarantee this even when unrelated code (or a listener) calls
# <file>.close() directly, we intercept close() on the file objects handed to
# the loop.  Any such call is routed back to the owning event loop, which then
# performs a normal remove_listener() (releasing the fd through the loop).
#
# The loop must therefore never hold a registration for a fd that could be
# closed behind its back -- which is exactly what used to cause subtle bugs
# when a fd integer got reused after an external close().
# ---------------------------------------------------------------------------

# file object -> (EventLoop, listener) for every file under loop ownership
_owned_files = WeakKeyDictionary()
# classes whose close() was already patched at the class level
_patched_classes = set()


def _listener_initiated_close(file_):
    """Called when somebody invokes close() on a loop-owned file directly.

    Route the request back to the owning event loop so it can release the
    fd through the normal remove_listener() machinery.
    """
    owner = _owned_files.get(file_)
    if owner is None:
        # should not happen (the patched close only routes owned files here),
        # but stay safe: fall back to a plain close.
        try:
            file_.close()
        except Exception:
            pass
        return None
    ev_loop, listener = owner
    ev_loop.remove_listener(listener)
    return None


def _watch_file(f):
    """Ensure close() on file object ``f`` routes through the event loop.

    Returns the *real* bound close() method, to be used when the loop itself
    wants to release the fd (so that release is not re-intercepted).

    Two strategies are used:
      * class-level patching when the type allows it (uniform, done once per
        class -- works for classes like socket, and even some with __slots__),
      * instance-level patching otherwise (immutable types such as
        ``_io.BufferedReader``, or wrapper objects exposing close() through
        ``__getattr__`` rather than as a real class attribute).
    """
    cls = type(f)
    # make sure the watched file's close() is intercepted (done once per
    # class, or per instance for immutable types / __getattr__ wrappers).
    if cls not in _patched_classes:
        try:
            unbound = cls.__dict__.get('close')
        except Exception:
            unbound = None
        if unbound is not None:
            # class-level patch (done once per class)
            def close_wrapper(self, *a, **kw):
                if _owned_files.get(self) is not None:
                    return _listener_initiated_close(self)
                # not a loop-owned file: behave like the original close()
                return cls._evloop_orig_close.__get__(self, cls)(*a, **kw)
            try:
                cls._evloop_orig_close = unbound
                cls.close = close_wrapper
                _patched_classes.add(cls)
            except Exception:
                # immutable class -> fall back to instance-level patch
                unbound = None
        if unbound is None and not getattr(f, '_evloop_instance_patched', False):
            # instance-level patch (immutable class, or no class-level close).
            # NB: an instance attribute is *not* bound, so we capture the
            # specific instance ``f`` in the closure (the file object is not
            # passed to us when f.close() is invoked).
            original = f.close
            def close_wrapper(*a, **kw):
                if _owned_files.get(f) is not None:
                    return _listener_initiated_close(f)
                return original(*a, **kw)
            f.close = close_wrapper
            f._evloop_instance_patched = True
            f._evloop_instance_orig_close = original
    # resolve the real (unpatched) close() bound to this specific file, so
    # that when the loop itself releases the fd it never hits a wrapper.
    if getattr(cls, '_evloop_orig_close', None) is not None:
        return cls._evloop_orig_close.__get__(f, cls)
    if getattr(f, '_evloop_instance_patched', False):
        return f._evloop_instance_orig_close
    return f.close


# This object allows to implement ev_loop.auto_waitpid(<pid>, <wait_cb>=None)
class PIDListener:
    def __init__(self, pid, wait_cb=None):
        self._pid = pid
        self._pidfd = None
        self._wait_cb = wait_cb

    def start(self):
        # wrap the (int) pidfd into a file object so it can be handled by the
        # event loop exactly like any other watched file.
        self._pidfd = os.fdopen(os.pidfd_open(self._pid, 0), 'rb', buffering=0)

    def handle_event(self, ts):
        # the event loop calls this when the child is stopped
        return False  # let the event loop remove us and call close()

    def close(self):
        # the file (the wrapped pidfd) is closed by the event loop itself
        if self._wait_cb is None:
            os.waitpid(self._pid, 0)
        else:
            self._wait_cb()


class StreamListener:
    def __init__(self, popen_stream, stream_handler):
        self._popen_stream = popen_stream
        self._stream_handler = stream_handler

    def handle_event(self, ts):
        chunk = self._popen_stream.read(4096)
        if len(chunk) == 0:
            return False   # let the event loop remove us and close the stream
        self._stream_handler.write(chunk)

    def close(self):
        # the stream is closed by the event loop itself
        pass


# This object allows to implement ev_loop.do(<cmd>, <callback>)
class ProcessListener:
    _num_processes = 0

    def __init__(self, ev_loop, cmd, callback,
                 silent=True,
                 catch_stdout=False,
                 catch_stderr=False,
                 pipe_stdout=None,
                 pipe_stderr=None,
                 **ignored_kwargs):
        self._ev_loop = ev_loop
        self._cmd = cmd
        self._callback = callback
        self._silent = silent
        self._catch_stdout = catch_stdout
        self._catch_stderr = catch_stderr
        self._pipe_stdout = pipe_stdout
        self._pipe_stderr = pipe_stderr
        self._popen = None
        self._pidfd = None
        self.pid = None
        self.stdin = None

    def start(self):
        ProcessListener._num_processes += 1
        bufsize = -1  # default
        if self._catch_stdout:
            stdout = PIPE
        elif self._pipe_stdout is not None:
            stdout = PIPE
            bufsize = 0
        elif self._silent:
            stdout = DEVNULL
        else:
            stdout = None   # no redirection, print to parent stdout
        if self._catch_stderr:
            stderr = PIPE
        elif self._pipe_stderr is not None:
            stderr = PIPE
            bufsize = 0
        else:
            stderr = None   # no redirection, print to parent stdout
        self._popen = Popen(shlex.split(self._cmd),
                stdin=PIPE, stdout=stdout, stderr=stderr, bufsize=bufsize)
        if self._pipe_stdout is not None:
            self._add_stream_listener(self._popen.stdout, self._pipe_stdout)
        if self._pipe_stderr is not None:
            self._add_stream_listener(self._popen.stderr, self._pipe_stderr)
        # wrap the (int) pidfd into a file object so it can be handled by the
        # event loop exactly like any other watched file.
        self._pidfd = os.fdopen(os.pidfd_open(self._popen.pid, 0), 'rb', buffering=0)
        self.pid = self._popen.pid
        self.stdin = self._popen.stdin

    def _add_stream_listener(self, popen_stream, stream_handler):
        listener = StreamListener(popen_stream, stream_handler)
        self._ev_loop.register_listener(popen_stream, listener)

    def handle_event(self, ts):
        # the event loop calls this when the child is stopped
        return False  # let the event loop remove us and call close()

    def close(self):
        # the wrapped pidfd file is closed by the event loop itself
        retcode = self._popen.wait()
        ProcessListener._num_processes -= 1
        if self._callback is not None:
            kwargs = {}
            if self._catch_stdout:
                kwargs.update(stdout_msg=self._popen.stdout.read())
            if self._catch_stderr:
                kwargs.update(stderr_msg=self._popen.stderr.read())
            self._callback(retcode, **kwargs)


class PollersCache:
    def __init__(self):
        self._next_fds_id = 0
        self._fds_id_per_fds = {}
        self._fds_per_fds_id = {}
        self._fds_ids_per_fd = defaultdict(set)
        self._poller_per_fds_id = {}
        self._events_per_fd = {}
    def get(self, fds):
        fds_id = self._fds_id_per_fds.get(fds, self._next_fds_id)
        if fds_id == self._next_fds_id:
            self._fds_id_per_fds[fds] = fds_id
            self._fds_per_fds_id[fds_id] = fds
            #if current_process().name == "server-main":
            #    print("num fds:", len(self._fds_per_fds_id),
            #          "-- num fd:", len(self._events_per_fd))
            self._next_fds_id += 1
        poller = self._poller_per_fds_id.get(fds_id)
        if poller is None:
            poller = poll()
            [poller.register(fd, self._events_per_fd[fd]) for fd in fds]
            [self._fds_ids_per_fd[fd].add(fds_id) for fd in fds]
            self._poller_per_fds_id[fds_id] = poller
        return poller
    def register_fd(self, fd, events):
        #print(f"+ {fd}")
        self._events_per_fd[fd] = events
    def remove_fd(self, fd):
        #print(f"- {fd}")
        # remove all known fds which include fd
        for fds_id in self._fds_ids_per_fd[fd].copy():
            fds = self._fds_per_fds_id.pop(fds_id)
            del self._fds_id_per_fds[fds]
            [self._fds_ids_per_fd[_fd].discard(fds_id) for _fd in fds]
            self._poller_per_fds_id.pop(fds_id)
        # forget fd-specific info
        del self._events_per_fd[fd]
        del self._fds_ids_per_fd[fd]
    def update_fd(self, fd, events):
        #print(f"m {fd}")
        self._events_per_fd[fd] = events
        for fds_id in self._fds_ids_per_fd[fd]:
            self._poller_per_fds_id[fds_id].modify(fd, events)


# EventLoop allows to monitor incoming data on a set of
# file descriptors, and call the appropriate listener when
# input data is detected.
# Any number of listeners may be added, by calling
# register_listener().
# In case of error, the file descriptor is removed from
# the set of watched descriptors.
# When the set is empty, the loop stops.
class EventLoop(object):
    MAX_TIMEOUT_MS = 500

    def __init__(self):
        self._pollers = PollersCache()
        self.listeners_per_fd = {}
        self.planned_events = []
        self.recursion_depth = 0
        self.pending_events = {}
        self._disabled_fds = set()
        # by default self.idle_section_hook does nothing, but
        # the caller can set this attribute with a context
        # manager object if needed.
        self.idle_section_hook = contextlib.nullcontext

    def has_bg_processes(self):
        return ProcessListener._num_processes > 0

    def get_polling_fds(self, single_listener=None):
        if single_listener is None:
            return tuple(sorted(set(self.listeners_per_fd.keys()) - self._disabled_fds))
        else:
            return (single_listener._ev_loop_fd,)

    def pop_pending_event(self, single_listener=None):
        if len(self.pending_events) == 0:
            return None, None, None
        if single_listener is None:
            fd = next(iter(self.pending_events.keys()))
        else:
            fd = single_listener._ev_loop_fd
            if fd not in self.pending_events:
                return None, None, None
        ev, ts = self.pending_events.pop(fd)
        return fd, ev, ts

    def plan_event(self, ts, target=None, callback=None, repeat_delay=None, **kwargs):
        # Note: We have the risk of planning several events at the same time.
        # (e.g. clock sync at node bootup.)
        # In this case, other elements of the tuple will be taken into account
        # for the sort, which will result in an exception (kwargs is a dict and
        # dict is not an orderable type). In order to avoid this, we insert
        # id(kwargs) as a second element in the tuple.
        if target is not None:
            callback = target.handle_planned_event
        assert callback is not None, "Must specify either target or callback"
        heappush(self.planned_events, (ts, id(kwargs), callback, repeat_delay, kwargs))

    def waiting_for_planned_events(self, single_listener=None):
        # do not handle planned events in single listener mode
        return (single_listener is None) and (len(self.planned_events) > 0)

    def get_timeout(self, **opts):
        if not self.waiting_for_planned_events(**opts):
            return EventLoop.MAX_TIMEOUT_MS
        else:
            delay_ms = (self.planned_events[0][0] - time()) * 1000
            return max(0, min(EventLoop.MAX_TIMEOUT_MS, delay_ms))

    def update_listener(self, listener, events=POLL_OPS_READ):
        fd = listener._ev_loop_fd
        self._pollers.update_fd(fd, events)
        # discard previous pending events for this fd
        # since we are no longer waiting for the same kind of event
        if fd in self.pending_events:
            del self.pending_events[fd]

    def register_listener(self, f, listener, /, *, events=POLL_OPS_READ):
        """Register ``listener`` for the file object ``f``.

        ``f`` and ``listener`` must be passed positionally; ``events`` is
        keyword-only.  The event loop takes ownership of ``f``: it is the only
        component allowed to close it, and any direct call to ``f.close()`` is
        intercepted and routed back through the loop (see _watch_file()).
        """
        if not hasattr(f, 'fileno'):
            raise TypeError(
                f"register_listener expected a file object as first argument, got {f!r}")
        fd = f.fileno()
        assert isinstance(fd, int) and fd >= 0
        # take ownership of the file: intercept direct close() calls; remember
        # the real close() so the loop itself can release the fd.
        real_close = _watch_file(f)
        listener._ev_loop_fd = fd
        listener._evloop_file = f
        listener._evloop_real_close = real_close
        # record ownership so that _listener_initiated_close() can find us back
        _owned_files[f] = (self, listener)
        self._pollers.register_fd(fd, events)
        self.listeners_per_fd[fd] = listener
        # print 'new listener:', listener

    def remove_listener(self, listener):
        if not hasattr(listener, "_ev_loop_fd"):
            return False  # listener was already removed previously
        fd = listener._ev_loop_fd
        f = getattr(listener, "_evloop_file", None)
        real_close = getattr(listener, "_evloop_real_close", None)
        delattr(listener, "_ev_loop_fd")
        if hasattr(listener, "_evloop_file"):
            delattr(listener, "_evloop_file")
        if hasattr(listener, "_evloop_real_close"):
            delattr(listener, "_evloop_real_close")
        self._pollers.remove_fd(fd)
        del self.listeners_per_fd[fd]
        if fd in self.pending_events:
            del self.pending_events[fd]
        # release our ownership of the file first, so that a close() performed
        # by listener.close() below (if any) is not re-intercepted by the loop.
        if f is not None:
            _owned_files.pop(f, None)
        try:
            listener.close()
        except Exception as e:
            print(f"Warning, closing {listener} failed: {e}")
        if f is not None and real_close is not None:
            try:
                real_close()
            except Exception as e:
                print(f"Warning, closing {listener}'s file failed: {e}")
        return True  # done

    def should_continue(self, loop_condition):
        if loop_condition is None:
            return True
        return loop_condition()

    def reordering_allowed(self, fd):
        listener = self.listeners_per_fd[fd]
        return getattr(listener, "allow_reordering", False)

    @contextlib.contextmanager
    def signals_allowed(self):
        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGHUP])
        try:
            yield
        finally:
            signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGHUP])

    def loop(self, loop_condition=None, single_listener=None):
        self.recursion_depth += 1
        opts = dict(single_listener=single_listener)
        poller = None
        # print(f'__DEBUG__ {current_process().name} loop depth={self.recursion_depth}')
        while True:
            # handle any expired planned event
            if self.waiting_for_planned_events(**opts):
                should_continue = True
                now = time()
                while len(self.planned_events) > 0 and self.planned_events[0][0] <= now:
                    ev = heappop(self.planned_events)
                    ts, kwargs_id, callback, repeat_delay, kwargs = ev
                    callback(**kwargs)
                    poller = None  # list of fds should be recomputed after this callback
                    if repeat_delay:
                        next_ts = ts + repeat_delay
                        if next_ts < now:  # we are very late
                            next_ts = now + repeat_delay  # reschedule
                        self.plan_event(
                            next_ts,
                            callback=callback,
                            repeat_delay=repeat_delay,
                            **kwargs
                        )
                    # if this planned event fulfilled the condition, quit
                    should_continue = self.should_continue(loop_condition)
                    if not should_continue:
                        break  # this will just break the inner while loop
                if not should_continue:
                    break  # break the outer while loop
            fd, ev, ts = self.pop_pending_event(**opts)
            if fd is None:
                # stop the loop if no more listeners
                if len(self.listeners_per_fd) == 0:
                    break
                # get a poller object for the file descriptors we monitor
                if poller is None:
                    fds = self.get_polling_fds(**opts)
                    poller = self._pollers.get(fds)
                # first check if we have pending file descriptor notifications
                # we should process right away
                res = poller.poll(0)   # timeout = 0
                if len(res) == 0:
                    # compute timeout
                    timeout = self.get_timeout(**opts)
                    if timeout == 0:
                        continue    # we are late, run planned events
                    # we known we will really wait, allow signals to interrupt
                    with self.signals_allowed():
                        # if signals were pending, signal handlers were called
                        # immediately after we allowed them, so loop_condition
                        # status may have changed.
                        if not self.should_continue(loop_condition):
                            break
                        with self.idle_section_hook():
                            res = poller.poll(timeout)
                if len(res) == 0:
                    continue  # poll() was stopped because of the timeout
                # save the time of the events
                ts = time()
                # continue below with the 1st of these new events, and save
                # others in self.pending_events
                for fd, ev in res[1:]:
                    self.pending_events[fd] = (ev, ts)
                fd, ev = res[0]
            # Process an event.
            # Note: we have to keep in mind the possible resursive calls to the
            # event loop, causing self.pending_events to be modified while we run
            # listener.handle_event() below.
            listener = self.listeners_per_fd[fd]
            # if error, we will remove the listener below
            should_close = not is_event_ok(ev)
            if not should_close:  # no error
                # unless the listener allows event reordering, we prevent the event loop
                # to process a future event recursively (while processing
                # listener.handle_event(ts)) on the same listener by temporarily
                # disabling it.
                allow_reordering = self.reordering_allowed(fd)
                if not allow_reordering:
                    self._disabled_fds.add(fd)
                # let the listener handle the event
                res = listener.handle_event(ts)
                # restore listener if it was temporarily disabled
                if not allow_reordering:
                    self._disabled_fds.discard(fd)
                # if False was returned, we will
                # close this listener.
                should_close = res is False
            if should_close:
                self.remove_listener(listener)
            # the list of fds should be recomputed after listener.handle_event()
            # and possibly listener.close()
            poller = None
            # if previous listener callback fulfilled the condition, quit
            if not self.should_continue(loop_condition):
                break
        # print(f'__DEBUG__ {current_process().name} end depth={self.recursion_depth}')
        self.recursion_depth -= 1

    def do(self, cmd, callback=None, silent=True, **kwargs):
        if callback is None:
            callback = functools.partial(self._check_retcode, cmd)
        kwargs.update(
            cmd = cmd,
            ev_loop = self,
            callback = callback,
            silent = silent,
        )
        p = ProcessListener(**kwargs)
        p.start()
        self.register_listener(p._pidfd, p)
        return p

    def _check_retcode(self, cmd, retcode):
        if retcode != 0:
            raise Exception(f"Failed call to: {cmd}!")

    # This function works with server's Worflow objects
    def wf_do(self, wf, cmd, *args, **kwargs):
        if kwargs.get("raise_exception", True):
            cb = functools.partial(self._wf_check_retcode, wf, cmd)
        else:
            cb = functools.partial(self._wf_save_retcode, wf)
        self.do(cmd, cb, *args, **kwargs)

    def _wf_check_retcode(self, wf, cmd, retcode):
        self._check_retcode(cmd, retcode)
        wf.next()

    def _wf_save_retcode(self, wf, retcode):
        wf.update_env(retcode=retcode)
        wf.next()

    def auto_waitpid(self, pid, wait_cb=None):
        p = PIDListener(pid, wait_cb)
        p.start()
        self.register_listener(p._pidfd, p)
