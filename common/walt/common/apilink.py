#!/usr/bin/env python
import rpyc, time, os, sys, inspect
from select import select
from datetime import datetime, timedelta
from multiprocessing import Queue
import Queue as QueueException
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.api import api, api_expose_method
from walt.common.reusable import reusable
from walt.common.tools import BusyIndicator

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

# Sometimes we start a long running process on the server and wait for
# its completion. In this case, while we are waiting, the server may
# send rpyc requests to update the client stdout or stderr.
# This object provide methods to wait() and still be able to accept
# rpyc requests.
MAX_BLOCKING_TIME = 0.1

class Fake(object):
    def __getattr__(self, attr):
        return lambda: None

@reusable
class ServerAPIConnection(object):
    def __init__(self, server_ip, local_service, target_api):
        self.queue = local_service.queue
        self.target_api = target_api
        self.rpyc_conn = rpyc.connect(
                server_ip,
                WALT_SERVER_DAEMON_PORT,
                service = local_service)
        is_interactive = os.isatty(sys.stdout.fileno()) and \
                            os.isatty(sys.stdin.fileno())
        if is_interactive:
            self.indicator = BusyIndicator('Server is working')
        else:
            self.indicator = Fake()
    def __getattr__(self, attr):
        def remote_func_caller(*args, **kwargs):
            # start api call
            self.rpyc_conn.root.api_call(\
                    self.target_api, attr, *args, **kwargs)
            # walt for the result and return it
            return self.wait_queue()
        return remote_func_caller
    def get_remote_api_version(self):
        return self.rpyc_conn.root.get_api_version(self.target_api)
    def wait_cond(self, condition_func, timeout_func = None):
        self.indicator.start()
        while condition_func():
            self.indicator.update()
            timeout = MAX_BLOCKING_TIME
            if timeout_func:
                timeout = min(timeout_func(), timeout)
            r, w, e = select((self.rpyc_conn,), (), (self.rpyc_conn,), timeout)
            if len(e) > 0:  # if error
                break
            if len(r) == 0: # if timeout
                continue
            # otherwise, there is something to process on the rpyc connection
            self.indicator.reset()  # apparently the server is no longer busy
            self.rpyc_conn.serve()  # process the request
        self.indicator.done()
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
    def __del__(self):
        self.rpyc_conn.close()

@APIService
class VoidAPIService(object):
    pass

# This class provides a 'with' environment to connect to
# the server API.
class ServerAPILink(object):
    def __init__(self, server_ip, target_api, local_service = None):
        if local_service == None:
            local_service = VoidAPIService()
        self.conn = ServerAPIConnection(
            server_ip,
            local_service,
            target_api)
    def __enter__(self):
        return self.conn
    def __exit__(self, type, value, traceback):
        # do not close the connection right now, it might be reused
        # thanks to the @reusable decorator of ServerAPIConnection
        pass

