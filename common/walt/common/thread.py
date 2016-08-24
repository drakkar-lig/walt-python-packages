import sys, signal
from multiprocessing import Pipe
from threading import Thread
from walt.common.evloop import EventLoop
from walt.common.tools import AutoCleaner

class EvThread(Thread):
    def __init__(self, manager):
        Thread.__init__(self)
        self.ev_loop = EventLoop()
        self.pipe_in, self.pipe_out = Pipe() 
        self.ev_loop.register_listener(self)
        manager.register_thread(self)

    # mimic an event loop
    def __getattr__(self, attr):
        return getattr(self.ev_loop, attr)

    def run(self):
        with AutoCleaner(self):
            self.prepare()
            self.ev_loop.loop()
        
    def fileno(self):
        return self.pipe_in.fileno()

    def forward_exception(self, e):
        self.pipe_out.send(e)

    def handle_event(self, ts):
        e = self.pipe_in.recv()
        print 'Got exception', e
        sys.stdout.flush()
        self.cleanup()
        raise e

    def prepare(self):
        pass    # optionally override in subclass

    def cleanup(self):
        pass    # optionally override in subclass

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

