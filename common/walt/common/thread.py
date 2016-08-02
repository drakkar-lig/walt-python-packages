import sys, signal
from multiprocessing import Pipe
from threading import Thread
from walt.common.evloop import EventLoop

class EvThread(Thread):
    def __init__(self, manager):
        Thread.__init__(self)
        self.evloop = EventLoop()
        self.pipe_in, self.pipe_out = Pipe() 
        self.evloop.register_listener(self)
        manager.register_thread(self)

    def register_listener(self, listener, *args, **kwargs):
        listener.thread = self
        self.evloop.register_listener(listener, *args, **kwargs)

    def run(self):
        for l in self.evloop.listeners.values():
            if hasattr(l, 'prepare'):
                l.prepare(self.evloop)
        self.evloop.loop()
        
    def fileno(self):
        return self.pipe_in.fileno()

    def forward_exception(self, e):
        self.pipe_out.send(e)

    def handle_event(self, ts):
        e = self.pipe_in.recv()
        print 'Got exception', e
        sys.stdout.flush()
        raise e

class EvThreadsManager(object):
    def __init__(self):
        self.threads = []
    def register_thread(self, t):
        self.threads.append(t)
    def start(self):
        try:
            for t in self.threads:
                t.start()
            signal.pause()
        except BaseException as e:
            print 'initial exception', e
            sys.stdout.flush()
            for t in self.threads:
                t.forward_exception(e)

