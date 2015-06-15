#!/usr/bin/env python
import os, sys
from select import poll, POLLIN, POLLPRI, POLLOUT

POLL_OPS_READ = POLLIN | POLLPRI

def is_read_event_ok(ev):
    # check that there is nothing more
    # than the events we were looking at
    # (i.e. POLLIN, POLLPRI but 
    # not POLLERR, POLLUP or POLLNVAL)
    return (ev & (~POLL_OPS_READ) == 0)

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
        print 'new listener:', listener

    def remove_listener(self, in_listener):
        print 'removing ' + str(in_listener)
        sys.stdout.flush()
        # find fd
        for fd, listener in self.listeners.iteritems():
            if listener is in_listener:
                break
        listener.close()
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
            sys.stdout.flush()

# This function allows to disable buffering
# of a file.
# CAUTION: since we use the fileno() method,
# this will not work when called on a remote
# (RPyC) object (the filedescriptor integer
# is only relevant on the local machine...)
def unbuffered(f, mode):
    # we need to duplicate the filedescriptor
    # in order to avoid the same filedescriptor 
    # to be closed several times
    return os.fdopen(os.dup(f.fileno()), mode, 0)

# The following class allows to read all
# chars pending in a file object.
class SmartBufferingFileReader(object):
    def __init__(self, in_file):
        self.in_file = in_file
        self.poller = poll()
        self.poller.register(self.in_file, POLL_OPS_READ)
    def read_available(self):
        # continue reading until there
        # is nothing more to read
        s = ''
        while True:
            # timeout=0, do not block
            res = self.poller.poll(0)
            if len(res) == 0:   # no event (timeout)
                break
            fd, ev = res[0]
            if not is_read_event_ok(ev):
                break
            c = self.in_file.read(1)
            if c == '':
                break   # empty read
            s += c
        return s
    def readline(self):
        return self.in_file.readline()

def read_and_copy(in_reader, out):
    buf = in_reader.read_available()
    if buf == '':
        return False    # close
    out.write(buf)
    out.flush()

