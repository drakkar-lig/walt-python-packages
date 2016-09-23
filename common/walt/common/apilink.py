#!/usr/bin/env python
import rpyc, time, sys, inspect
from datetime import datetime, timedelta
from multiprocessing import Queue
import Queue as QueueException
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.api import api, api_expose_method

# Shared Queue allowing to wait for the remote API result
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


# This decorator allows to define RPyC-based API service classes
# with a customized __init__ function.
# (without it, one has to conform to the prototype of the base
# class rpyc.Service.__init__(), because the rpyc core
# instanciates such a service itself.)
def APIService(cls):
    # caution: cls must be the first base class in order to be
    # first in the method resolution order (e.g. regarding on_connect()).
    def mixed_cls_generator(*cls_args, **cls_kwargs):
        class Mixed(cls, rpyc.Service):
            queue = ResponseQueue()
            def __init__(self, *args, **kwargs):
                rpyc.Service.__init__(self, *args, **kwargs)
                cls.__init__(self, *cls_args, **cls_kwargs)
                self.queue = Mixed.queue
                self.exposed_queue = self.queue
        return Mixed
    return mixed_cls_generator

# This class allows to build RPyC proxies for the following scenario:
# process1 <--rpyc-link--> process2 <--rpyc-link--> process3
# If process2 wants to expose objects of process1 directly to process3,
# it will not work directly because of the 2 layers of 'exposed_' prefixes.
# In this case it should return RPyCProxy(<object>) instead.
class RPyCProxy(object):
    def __init__(self, remote_obj, path=(), ignore_spec=()):
        self.remote_obj = remote_obj
        self.path = path
        self.ignore_spec = ignore_spec
    def __getattr__(self, attr):
        if not attr.startswith('exposed_'):
            return None
        # discard the 'exposed_' prefix
        attr = attr[8:]
        try:
            if not hasattr(self.remote_obj, attr):
                return None
            obj = getattr(self.remote_obj, attr)
            if inspect.ismethod(obj):
                # recursively return a proxy for this method
                return RPyCProxy(obj, self.ignore_spec)
            else:
                return obj
        except self.ignore_spec:
            return None
    def __call__(self, *args, **kwargs):
        # if we are here, the remote object should also be callable...
        # call it and return the result.
        try:
            return self.remote_obj(*args, **kwargs)
        except self.ignore_spec:
            return None


# Sometimes we start a long running process on the server and wait for
# its completion. In this case, while we are waiting, the server may
# send rpyc requests to update the client stdout or stderr.
# This object provide methods to wait() and still be able to accept
# rpyc requests.
MAX_BLOCKING_TIME = 0.1

class ServerAPIConnection(object):
    def __init__(self, rpyc_conn, queue):
        self.rpyc_conn = rpyc_conn
        self.queue = queue
    def __getattr__(self, attr):
        def remote_func_caller(*args, **kwargs):
            # lookup remote api function
            remote_func = getattr(self.rpyc_conn.root, attr)
            # let the hub thread plan execution
            remote_func(*args, **kwargs)
            # walt for the result and return it
            return self.wait_queue()
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
    def wait_queue(self):
        def condition_func():
            return self.queue.empty()
        self.wait_cond(condition_func)
        return self.queue.get()
    def close(self):
        return self.rpyc_conn.close()

# This class provides a 'with' environment to connect to
# the server API.
class ServerAPILink(object):
    def __init__(self, server_ip, target_api, local_service):
        self.server_ip = server_ip
        self.local_service = local_service
        self.target_api = target_api
    def __enter__(self):
        self.conn = ServerAPIConnection(
            rpyc.connect(
                self.server_ip,
                WALT_SERVER_DAEMON_PORT,
                service = self.local_service),
            self.local_service.queue)
        self.conn.select_api(self.target_api)
        return self.conn
    def __exit__(self, type, value, traceback):
        self.conn.close()

