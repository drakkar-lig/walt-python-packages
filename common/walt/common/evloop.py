#!/usr/bin/env python
import os, sys
from select import poll, select, POLLIN, POLLPRI
from time import time
from heapq import heappush, heappop

POLL_OPS_READ = POLLIN | POLLPRI

def is_read_event_ok(ev):
    # check that there is something to read
    # (i.e. POLLIN or POLLPRI)
    return (ev & (POLL_OPS_READ) > 0)

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
        self.listeners = {}
        self.planned_events = []
        self.poller = poll()

    def plan_event(self, ts, target, repeat_delay = None, **kwargs):
        heappush(self.planned_events,
                 (ts, target, repeat_delay, kwargs))

    def get_timeout(self):
        if len(self.planned_events) == 0:
            return None
        else:
            return (self.planned_events[0][0] - time())*1000

    def update_listener(self, listener, events=POLL_OPS_READ):
        fd = listener.fileno()
        self.poller.unregister(fd)
        self.poller.register(fd, events)

    def register_listener(self, listener, events=POLL_OPS_READ):
        fd = listener.fileno()
        self.listeners[fd] = listener
        self.poller.register(fd, events)
        #print 'new listener:', listener

    def remove_listener(self, in_listener):
        #print 'removing ' + str(in_listener)
        #sys.stdout.flush()
        # find fd
        for fd, listener in self.listeners.iteritems():
            if listener is in_listener:
                break
        # do no fail in case of issue in listener.close()
        # because anyway we do not need this listener anymore
        try:
            listener.close()
        except Exception as e:
            print 'warning: got exception in listener.close():', e
        del self.listeners[fd]
        self.poller.unregister(fd)

    def loop(self):
        while True:
            # handle any expired planned event
            now = time()
            while len(self.planned_events) > 0 and \
                        self.planned_events[0][0] <= now:
                ts, target, repeat_delay, kwargs = \
                                    heappop(self.planned_events)
                target.handle_planned_event(**kwargs)
                if repeat_delay:
                    next_ts = ts + repeat_delay
                    if next_ts < now:                   # we are very late
                        next_ts = now + repeat_delay    # reschedule
                    self.plan_event(
                        next_ts, target, repeat_delay, **kwargs)
            # if a listener provides a method is_valid(),
            # check it and remove it if result is False
            for listener in self.listeners.values():
                try:
                    if listener.is_valid() == False:
                        # some data may have been buffered, we check this.
                        # (if this is the case, then we will delay the
                        # removal of this listener)
                        r, w, x = select([listener], [], [], 0)
                        if len(r) == 0:     # ok, no data
                            self.remove_listener(listener)
                except AttributeError:
                    pass # this listener does not implement is_valid()
            # stop the loop if no more listeners
            if len(self.listeners) == 0:
                break
            # wait for an event
            res = self.poller.poll(self.get_timeout())
            # save the time of the event as soon as possible
            ts = time()
            if len(res) == 0:
                continue    # poll() was stopped because of the timeout
            # process the event
            fd, ev = res[0]
            listener = self.listeners[fd]
            # if error, we will remove the listener below
            should_close = not is_read_event_ok(ev)
            if not should_close:
                # no error, let the listener
                # handle the event
                res = listener.handle_event(ts)
                # if False was returned, we will
                # close this listener.
                should_close = (res == False)
            if should_close:
                self.remove_listener(listener)

