#!/usr/bin/env python
import rpyc, time, os, sys, signal, threading
from datetime import datetime, timedelta
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.tools import do
from walt.client.config import conf
from walt.client.filesystem import Filesystem
from multiprocessing import Queue
import Queue as QueueException
from walt.common.api import api, api_expose_method, api_expose_attrs

@api
class ResponseQueue(object):
    def __init__(self):
        self.q = Queue()
    @api_expose_method
    def put(self, *args, **kwargs):
        self.q.put(*args, **kwargs)
    @api_expose_method
    def done(self):
        self.q.put(None)
    def empty(self):
        return self.q.empty()
    def get(self):
        # loop to avoid blocking in case of ctrl-C
        res = None
        while True:
            try:
                res = self.q.get(timeout = 0.1)
                break
            except QueueException.Empty:
                pass
        return res
    def wait(self):
        self.get()

@api
class ExposedStream(object):
    def __init__(self, stream):
        self.stream = stream
    @api_expose_method
    def fileno(self):
        return self.stream.fileno()
    @api_expose_method
    def readline(self, size=-1):
        return self.stream.readline(size)
    @api_expose_method
    def write(self, s):
        self.stream.write(s)
    @api_expose_method
    def flush(self):
        self.stream.flush()

# most of the functionality is provided at the server,
# of course.
# but the client also exposes a few objects / features
# in the following class.
@api
class WaltClientService(rpyc.Service):
    queue = None
    @api_expose_attrs('stdin','stdout','stderr','username','filesystem','queue')
    def __init__(self, *args, **kwargs):
        rpyc.Service.__init__(self, *args, **kwargs)
        self.stdin = ExposedStream(sys.stdin)
        self.stdout = ExposedStream(sys.stdout)
        self.stderr = ExposedStream(sys.stderr)
        self.username = conf['username']
        self.filesystem = Filesystem()
        self.queue = WaltClientService.queue

WaltClientService.queue = ResponseQueue()

# Sometimes we start a long running process on the server and wait for
# its completion. In this case, while we are waiting, the server may
# send rpyc requests to update the client stdout or stderr.
# This object provide methods to wait() and still be able to accept
# rpyc requests.
MAX_BLOCKING_TIME = 0.1

class ServerConnection(object):
    def __init__(self, rpyc_conn):
        self.rpyc_conn = rpyc_conn
    def __getattr__(self, attr):
        def remote_func_caller(*args, **kwargs):
            # lookup remote api function
            remote_func = getattr(self.rpyc_conn.root, attr)
            # let the hub thread plan execution
            remote_func(*args, **kwargs)
            # walt for the result and return it
            return self.wait_queue(WaltClientService.queue)
        return remote_func_caller
    def wait_cond(self, condition_func, timeout_func = None):
        while condition_func():
            self.update_progress_indicator()
            timeout = MAX_BLOCKING_TIME
            if timeout_func:
                timeout = min(timeout_func(), timeout)
            self.rpyc_conn.serve(timeout = timeout)
    def update_progress_indicator(self):
        idx = int(time.time()*2) % 4
        progress = "\\|/-"[idx]
        sys.stdout.write('\r' + progress + '\r')
        sys.stdout.flush()
    def wait(self, max_secs):
        time_max = datetime.now() + timedelta(seconds=max_secs)
        def condition_func():
            return datetime.now() < time_max
        def timeout_func():
            return (datetime.now() - time_max).total_seconds()
        self.wait_cond(condition_func, timeout_func)
    def wait_queue(self, q):
        def condition_func():
            return q.empty()
        self.wait_cond(condition_func)
        return q.get()
    def close(self):
        return self.rpyc_conn.close()

class ClientToServerLink:
    def __enter__(self):
        self.conn = ServerConnection(rpyc.connect(
                conf['server'],
                WALT_SERVER_DAEMON_PORT,
                service = WaltClientService))
        return self.conn
    def __exit__(self, type, value, traceback):
        self.conn.close()

