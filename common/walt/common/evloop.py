#!/usr/bin/env python
import os, sys
from select import poll, POLLIN, POLLPRI

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
        self.poller = poll()

    def register_listener(self, listener):
        fd = listener.fileno()
        if fd == None:
            return  # registration aborted
        self.listeners[fd] = listener
        self.poller.register(fd, POLL_OPS_READ)
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
            # if a listener provides a method is_valid(),
            # check it and remove it if result is False
            for listener in self.listeners.values():
                try:
                    if listener.is_valid() == False:
                        self.remove_listener(listener)
                except AttributeError:
                    pass # this listener does not implement is_valid()
            # stop the loop if no more listeners
            if len(self.listeners) == 0:
                break
            # wait for an event
            fd, ev = self.poller.poll()[0]
            listener = self.listeners[fd]
            # if error, we will remove the listener below
            should_close = not is_read_event_ok(ev)
            if not should_close:
                # no error, let the listener
                # handle the event
                res = listener.handle_event()
                # if False was returned, we will
                # close this listener.
                should_close = (res == False)
            if should_close:
                self.remove_listener(listener)

