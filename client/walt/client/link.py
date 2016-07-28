#!/usr/bin/env python
import rpyc, os, sys, signal, threading
from datetime import datetime, timedelta
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.tools import do
from walt.client.config import conf
from walt.client.filesystem import Filesystem
from multiprocessing import Queue
from Queue import Queue as QueueException
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
    def get(self):
        # loop to avoid blocking in case of ctrl-C
        res = None
        while res == None:
            try:
                res = self.q.get(0.1)
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
    @api_expose_attrs('stdin','stdout','stderr','username','filesystem')
    def __init__(self, *args, **kwargs):
        rpyc.Service.__init__(self, *args, **kwargs)
        self.stdin = ExposedStream(sys.stdin)
        self.stdout = ExposedStream(sys.stdout)
        self.stderr = ExposedStream(sys.stderr)
        self.username = conf['username']
        self.filesystem = Filesystem()

# Sometimes we start a long running process on the server and wait for
# its completion. In this case, while we are waiting, the server may
# send rpyc requests to update the client stdout or stderr.
# This object provide methods to wait() and still be able to accept
# rpyc requests.
class ServerConnection(object):
    def __init__(self, rpyc_conn):
        self.rpyc_conn = rpyc_conn
    def __getattr__(self, attr):
        return getattr(self.rpyc_conn.root.cs, attr)
    def wait_cond(self, condition_func, timeout_func = lambda : None):
        while condition_func():
            self.rpyc_conn.serve(timeout = timeout_func())
    def wait(self, max_secs):
        time_max = datetime.now() + timedelta(seconds=max_secs)
        def condition_func():
            return datetime.now() < time_max
        def timeout_func():
            return (datetime.now() - time_max).total_seconds()
        self.wait_cond(condition_func, timeout_func)
    def wait_queue(self, q):
        def condition_func():
            return q.size() == 0
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

