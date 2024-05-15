#!/usr/bin/env python
import contextlib
import os
import signal
from heapq import heappop, heappush
from multiprocessing import current_process  # noqa: F401
from select import POLLIN, POLLOUT, POLLPRI, poll, select
from subprocess import PIPE, Popen, DEVNULL
from time import time


class BreakLoopRequested(Exception):
    pass


POLL_OPS_READ = POLLIN | POLLPRI
POLL_OPS_WRITE = POLLOUT


def is_event_ok(ev):
    # check that there is something to read or write
    return ev & (POLL_OPS_READ | POLL_OPS_WRITE) > 0


# This object allows to implement ev_loop.auto_waitpid(<pid>, <wait_cb>=None)
class PIDListener:
    def __init__(self, pid, wait_cb=None):
        self._pid = pid
        self._pidfd = None
        self._wait_cb = wait_cb

    def start(self):
        self._pidfd = os.pidfd_open(self._pid, 0)

    def fileno(self):
        return self._pidfd

    def handle_event(self, ts):
        # the event loop calls this when the child is stopped
        return False  # let the event loop remove us and call close()

    def close(self):
        os.close(self._pidfd)
        if self._wait_cb is None:
            os.waitpid(self._pid, 0)
        else:
            self._wait_cb()


# This object allows to implement ev_loop.do(<cmd>, <callback>)
class ProcessListener:
    def __init__(self, cmd, callback, silent):
        self._cmd = cmd
        self._callback = callback
        self._silent = silent
        self._popen = None
        self._pidfd = None

    def start(self):
        if self._silent:
            stdout = DEVNULL
        else:
            stdout = None   # no redirection, print to parent stdout
        self._popen = Popen(self._cmd, stdout=stdout, shell=True)
        self._pidfd = os.pidfd_open(self._popen.pid, 0)

    def fileno(self):
        return self._pidfd

    def handle_event(self, ts):
        # the event loop calls this when the child is stopped
        return False  # let the event loop remove us and call close()

    def close(self):
        os.close(self._pidfd)
        retcode = self._popen.wait()
        if self._callback is not None:
            self._callback(retcode)


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
        self.listeners_per_fd = {}
        self.events_per_fd = {}
        self.fd_per_listener_id = {}
        self.planned_events = []
        self.general_poller = poll()
        self.single_listener_pollers = {}
        self.recursion_depth = 0
        self.pending_events = {}
        self.disabled_listener = None
        # by default self.idle_section_hook does nothing, but
        # the caller can set this attribute with a context
        # manager object if needed.
        self.idle_section_hook = contextlib.nullcontext

    def get_poller(self, single_listener=None):
        if single_listener is None:
            return self.general_poller
        else:
            fd = single_listener.fileno()
            poller = self.single_listener_pollers.get(fd, None)
            if poller is None:
                events = self.events_per_fd[fd]
                poller = poll()
                poller.register(fd, events)
                self.single_listener_pollers[fd] = poller
            return poller

    def pop_pending_event(self, single_listener=None):
        if single_listener is None:
            if len(self.pending_events) == 0:
                return None, None, None
            fd = next(iter(self.pending_events.keys()))
        else:
            fd = single_listener.fileno()
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
        if single_listener is None:
            return len(self.planned_events) > 0
        else:
            # do not handle planned events in single listener mode
            return False

    def get_timeout(self, **opts):
        if not self.waiting_for_planned_events(**opts):
            return EventLoop.MAX_TIMEOUT_MS
        else:
            delay_ms = (self.planned_events[0][0] - time()) * 1000
            if delay_ms < 0:
                return 0
            else:
                return min(EventLoop.MAX_TIMEOUT_MS, delay_ms)

    def update_listener(self, listener, events=POLL_OPS_READ):
        fd = listener.fileno()
        self.events_per_fd[fd] = events
        # update general poller
        self.general_poller.modify(fd, events)
        # update single listener poller if it exists
        if fd in self.single_listener_pollers:
            self.single_listener_pollers[fd].modify(fd, events)
        # discard previous pending events for this fd
        # since we are no longer waiting for the same kind of event
        if fd in self.pending_events:
            del self.pending_events[fd]

    def register_listener(self, listener, events=POLL_OPS_READ):
        fd = listener.fileno()
        self.listeners_per_fd[fd] = listener
        self.events_per_fd[fd] = events
        self.fd_per_listener_id[id(listener)] = fd
        self.general_poller.register(fd, events)
        # print 'new listener:', listener

    def remove_listener(self, listener, should_close=True):
        listener_id = id(listener)
        fd = self.fd_per_listener_id.get(listener_id, None)
        if fd is None:
            return False  # listener was already removed previously
        del self.listeners_per_fd[fd]
        del self.events_per_fd[fd]
        del self.fd_per_listener_id[listener_id]
        if fd in self.pending_events:
            del self.pending_events[fd]
        if fd in self.single_listener_pollers:
            self.single_listener_pollers[fd].unregister(fd)
            del self.single_listener_pollers[fd]
        self.general_poller.unregister(fd)
        if should_close:
            listener.close()
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
        # in case of a recursive call to loop() while processing
        # listener.handle_event() with a listener that disallow
        # event reordering, we temporarily remove the listener
        # during this recursive call.
        disabled_listener_info = self.disabled_listener
        if disabled_listener_info is not None:
            disabled_listener, _ = disabled_listener_info
            # print(f'__DEBUG__ temp remove {listener}')
            self.remove_listener(disabled_listener, should_close=False)
            self.disabled_listener = None
        opts = dict(single_listener=single_listener)
        poller = self.get_poller(**opts)
        # print(f'__DEBUG__ {current_process().name} loop depth={self.recursion_depth}')
        while True:
            # if previous listener callback fulfilled the condition, quit
            if not self.should_continue(loop_condition):
                break
            # handle any expired planned event
            if self.waiting_for_planned_events(**opts):
                should_continue = True
                now = time()
                while len(self.planned_events) > 0 and self.planned_events[0][0] <= now:
                    ts, kwargs_id, callback, repeat_delay, kwargs = heappop(
                        self.planned_events
                    )
                    callback(**kwargs)
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
                for fd, ev in res:
                    self.pending_events[fd] = (ev, ts)
                fd, ev, ts = self.pop_pending_event(**opts)
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
                # disabling it. For performance, we actually call remove_listener()
                # (and then register_listener() to restore it) lazily in the recursive
                # call, if any, because those recursive calls are rare.
                allow_reordering = self.reordering_allowed(fd)
                if not allow_reordering:
                    events = self.events_per_fd[fd]
                    self.disabled_listener = (listener, events)
                # let the listener handle the event
                res = listener.handle_event(ts)
                # restore listener is it was temporarily removed
                if not allow_reordering:
                    self.disabled_listener = None
                # if False was returned, we will
                # close this listener.
                should_close = res is False
            if should_close:
                self.remove_listener(listener)
        # restore the temporarily disabled listener if any
        if disabled_listener_info is not None:
            disabled_listener, events = disabled_listener_info
            self.register_listener(disabled_listener, events)
            self.disabled_listener = disabled_listener_info
            # print(f'__DEBUG__ temp restore {disabled_listener}')
        # print(f'__DEBUG__ {current_process().name} end depth={self.recursion_depth}')
        self.recursion_depth -= 1

    def do(self, cmd, callback=None, silent=True):
        p = ProcessListener(cmd, callback, silent)
        p.start()
        self.register_listener(p)

    def auto_waitpid(self, pid, wait_cb=None):
        p = PIDListener(pid, wait_cb)
        p.start()
        self.register_listener(p)
