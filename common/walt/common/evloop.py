#!/usr/bin/env python
import os, sys
from subprocess import Popen, PIPE
from select import poll, select, POLLIN, POLLPRI, POLLOUT
from time import time
from heapq import heappush, heappop

class BreakLoopRequested(Exception):
    pass

POLL_OPS_READ = POLLIN | POLLPRI
POLL_OPS_WRITE = POLLOUT

def is_event_ok(ev):
    # check that there is something to read or write
    return (ev & (POLL_OPS_READ | POLL_OPS_WRITE) > 0)

# This object allows to implement ev_loop.do(<cmd>, <callback>)
class ProcessListener:
    def __init__(self, cmd, callback):
        # command should indicate when it is completed
        self.cmd = cmd + "; echo; echo __eventloop.ProcessListener.DONE__"
        self.callback = callback
        self.cmd_output = b''
    def run(self):
        self.popen = Popen(self.cmd, stdout = PIPE, shell = True)
    def fileno(self):
        return self.popen.stdout.fileno()
    # handle_event() will be called when the event loop detects
    # new input data for us.
    def handle_event(self, ts):
        data = self.popen.stdout.read(1024)
        if len(data) > 0:
            self.cmd_output += data
        if len(data) == 0 or \
           self.cmd_output.endswith(b'__eventloop.ProcessListener.DONE__\n'):
            # command terminated
            if self.callback is not None:
                self.callback()
            return False    # let event loop remove us
    def close(self):
        if self.popen is not None:
            self.popen.wait()

# EventLoop allows to monitor incoming data on a set of
# file descriptors, and call the appropriate listener when
# input data is detected.
# Any number of listeners may be added, by calling
# register_listener().
# In case of error, the file descriptor is removed from
# the set of watched descriptors.
# When the set is empty, the loop stops.

class EventLoop(object):
    def __init__(self):
        self.listeners_per_fd = {}
        self.fd_per_listener_id = {}
        self.fd_of_listeners_with_is_valid_method = set()
        self.planned_events = []
        self.poller = poll()

    def plan_event(self, ts, target = None, callback = None, repeat_delay = None, **kwargs):
        # Note: We have the risk of planning several events at the same time.
        # (e.g. clock sync at node bootup.)
        # In this case, other elements of the tuple will be taken into account
        # for the sort, which will result in an exception (kwargs is a dict and
        # dict is not an orderable type). In order to avoid this, we insert
        # id(kwargs) as a second element in the tuple.
        if target is not None:
            callback = target.handle_planned_event
        assert callback is not None, "Must specify either target or callback"
        heappush(self.planned_events,
                 (ts, id(kwargs), callback, repeat_delay, kwargs))

    def get_timeout(self):
        if len(self.planned_events) == 0:
            return None
        else:
            return (self.planned_events[0][0] - time())*1000

    def update_listener(self, listener, events=POLL_OPS_READ):
        self.remove_listener(listener, should_close=False)
        self.register_listener(listener, events)

    def register_listener(self, listener, events=POLL_OPS_READ):
        fd = listener.fileno()
        self.listeners_per_fd[fd] = listener
        self.fd_per_listener_id[id(listener)] = fd
        if hasattr(listener, 'is_valid'):
            self.fd_of_listeners_with_is_valid_method.add(fd)
        self.poller.register(fd, events)
        #print 'new listener:', listener

    def remove_listener(self, listener, should_close=True):
        listener_id = id(listener)
        fd = self.fd_per_listener_id[listener_id]
        del self.listeners_per_fd[fd]
        del self.fd_per_listener_id[listener_id]
        self.fd_of_listeners_with_is_valid_method.discard(fd)
        self.poller.unregister(fd)
        if not should_close:
            return  # done
        # do no fail in case of issue in listener.close()
        # because anyway we do not need this listener anymore
        try:
            listener.close()
        except BreakLoopRequested:
            raise
        except Exception as e:
            print('warning: got exception in listener.close():', repr(e))

    def loop(self, loop_condition = None):
        while True:
            if loop_condition is not None:
                if not loop_condition():
                    break
            # handle any expired planned event
            now = time()
            while len(self.planned_events) > 0 and \
                        self.planned_events[0][0] <= now:
                ts, kwargs_id, callback, repeat_delay, kwargs = \
                                    heappop(self.planned_events)
                callback(**kwargs)
                if repeat_delay:
                    next_ts = ts + repeat_delay
                    if next_ts < now:                   # we are very late
                        next_ts = now + repeat_delay    # reschedule
                    self.plan_event(
                        next_ts, callback = callback, repeat_delay = repeat_delay, **kwargs)
            # if a listener provides a method is_valid(),
            # check it and remove it if result is False
            for fd in tuple(self.fd_of_listeners_with_is_valid_method):
                listener = self.listeners_per_fd[fd]
                if listener.is_valid() == False:
                    # some data may have been buffered, we check this.
                    # (if this is the case, then we will delay the
                    # removal of this listener)
                    r, w, x = select([listener], [], [], 0)
                    if len(r) == 0:     # ok, no data
                        self.remove_listener(listener)
            # stop the loop if no more listeners
            if len(self.listeners_per_fd) == 0:
                break
            # wait for an event
            res = self.poller.poll(self.get_timeout())
            # save the time of the event as soon as possible
            ts = time()
            if len(res) == 0:
                continue    # poll() was stopped because of the timeout
            # process the events
            for fd, ev in res:
                listener = self.listeners_per_fd[fd]
                # if error, we will remove the listener below
                should_close = not is_event_ok(ev)
                if not should_close:
                    # no error, let the listener
                    # handle the event
                    res = listener.handle_event(ts)
                    # if False was returned, we will
                    # close this listener.
                    should_close = (res == False)
                if should_close:
                    self.remove_listener(listener)

    def do(self, cmd, callback = None):
        p = ProcessListener(cmd, callback)
        p.run()
        self.register_listener(p)

