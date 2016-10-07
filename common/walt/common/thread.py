import sys, signal, rpyc
from multiprocessing import Pipe
from rpyc.core.stream import PipeStream
from threading import Thread
from walt.common.evloop import EventLoop
from walt.common.tools import AutoCleaner

class EvThread(Thread):
    def __init__(self, manager, name):
        Thread.__init__(self, name = name)
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

class ThreadConnector(object):
    def __init__(self, rpyc_service = rpyc.VoidService):
        self.rpyc_service = rpyc_service
    def connect(self, remote):
        self.pipe, remote.pipe = Pipe()
        rpyc0, rpyc1 = PipeStream.create_pair()
        self.rpyc = rpyc.connect_stream(rpyc0, self.rpyc_service)
        remote.rpyc = rpyc.connect_stream(rpyc1, remote.rpyc_service)
    def close(self):
        self.pipe.close()
        self.rpyc.close()

