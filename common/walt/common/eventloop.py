#!/usr/bin/env python
from select import poll, POLLPRI, POLLIN, POLLERR

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
        self.listeners[fd] = listener
        self.poller.register(fd, POLLIN | POLLPRI | POLLERR)

    def loop(self):
        while len(self.listeners) > 0:
            fd, ev = self.poller.poll()[0]
            listener = self.listeners[fd]
            should_close = (ev == POLLERR)
            if not should_close:
                res = listener.handle_event()
                # if False was returned, we will
                # close this listener.
                should_close = (res == False)
            if should_close:
                listener.close()
                del self.listeners[fd]
                self.poller.unregister(fd)

