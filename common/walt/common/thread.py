import sys, signal, rpyc
from multiprocessing import Pipe
from rpyc.core.stream import PipeStream
from threading import Thread
from select import select
from walt.common.evloop import EventLoop
from walt.common.tools import AutoCleaner

class DownwardPropagatedException(Exception):
    pass

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
        try:
            with AutoCleaner(self):
                self.prepare()
                self.ev_loop.loop()
        except DownwardPropagatedException:
            print self.name + ' stopped because of propagated exception.'
        except BaseException as e:
            self.pipe_in.send(e) # propagate upward
            raise

    def fileno(self):
        return self.pipe_in.fileno()

    def forward_exception(self, e):
        self.pipe_out.send(e)

    def handle_event(self, ts):
        self.down_exception = self.pipe_in.recv()
        raise DownwardPropagatedException

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
            read_set = tuple(t.pipe_out for t in self.threads)
            r, w, e = select(read_set, (), read_set)
            e = r[0].recv()
            raise e
        except BaseException as e:
            # propagate downward to threads that are still alive
            for t in self.threads:
                try:
                    t.forward_exception(e)
                except:
                    pass

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

