#!/usr/bin/env python
import os, sys
from select import select
from socket import socket, error as SocketError
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.reusable import reusable
from walt.common.tools import BusyIndicator
from walt.common.tcp import Requests

# exceptions may occur if the client disconnects.
# we should ignore those.
class APIChannel(object):
    def __init__(self, sock_file):
        self.sock_file = sock_file
    def write(self, *args):
        if self.sock_file.closed:
            return
        self.sock_file.write(repr(args) + '\n')
    def read(self):
        if self.sock_file.closed:
            return None
        try:
            return eval(self.sock_file.readline())
        except (EOFError, SyntaxError, OSError, SocketError):
            return None
    def fileno(self):
        return self.sock_file.fileno()

# The following pair of classes allows to pass API calls efficiently
# over a network socket.
#
# On the emitter end, we will have the following kind of code:
#
# api = AttrCallAggregator(api_forwarding_func)
# ...
# res = api.my.super.function(1, 2, a=3)
#
# This will cause the following to be called:
# api_forwarding_func('my.super.function', [1, 2], {'a':3})
#
# then it is easy for api_backend_func to pass its arguments
# on the socket connection.
#
# on the other end, we have have a code like:
#
# api_call_runner = AttrCallRunner(api_handler)
# ...
# api_call_runner.do('my.super.function', [1, 2], {'a':3})
#
# This will call the following to be called:
# api_handler.my.super.function(1, 2, a=3)
#
# This mechanism is efficient because it sends the whole attribute path
# at once on the network.
# Drawback: It works with remote function calls only, i.e. you cannot
# read a remote attribute. Thus all remote attributes must be functions.

class AttrCallAggregator(object):
    def __init__(self, handler, path = ()):
        self.path = path
        self.handler = handler
    def __getattr__(self, attr):
        return AttrCallAggregator(self.handler, self.path + (attr,))
    def __call__(self, *args, **kwargs):
        path = '.'.join(self.path)
        return self.handler(path, args, kwargs)

class AttrCallRunner(object):
    def __init__(self, handler):
        self.handler = handler
    def do(self, path, args, kwargs):
        obj = self.handler
        for attr in path.split('.'):
            obj = getattr(obj, attr)
        return obj(*args, **kwargs)

# Sometimes we start a long running process on the server and wait for
# its completion. In this case, while we are waiting, the server may
# send api calls to update the client stdout or stderr.
# This object provide methods to wait() and still be able to accept
# these calls.
MAX_BLOCKING_TIME = 0.1

class Fake(object):
    def __getattr__(self, attr):
        return lambda: None
    def set_label(self, label):
        pass
    def set_default_label(self):
        pass

class LinkException(Exception):
    pass

DEFAULT_BUSY_LABEL = 'Server is working'

@reusable
class ServerAPIConnection(object):
    def __init__(self, server_ip, local_service, target_api):
        self.target_api = target_api
        self.server_ip = server_ip
        self.sock = socket()
        self.sock_file = self.sock.makefile('r+',0)
        self.api_channel = APIChannel(self.sock_file)
        self.remote_version = None
        is_interactive = os.isatty(sys.stdout.fileno()) and \
                            os.isatty(sys.stdin.fileno())
        self.client_proxy = AttrCallAggregator(self.handle_client_call)
        self.local_api_handler = AttrCallRunner(local_service)
        if is_interactive:
            self.indicator = BusyIndicator(DEFAULT_BUSY_LABEL)
        else:
            self.indicator = Fake()
        self.connected = False
    # since the object is reusable we must ensure we connect only once.
    def connect(self):
        if not self.connected:
            self.sock.connect((self.server_ip, WALT_SERVER_DAEMON_PORT))
            self.sock_file.write('%d\n%s\n' % (Requests.REQ_API_SESSION, self.target_api))
            self.remote_version = int(self.sock_file.readline().strip())
            self.connected = True
    def set_busy_label(self, label):
        self.indicator.set_label(label)
    def set_default_busy_label(self):
        self.indicator.set_default_label()
    def get_remote_version(self):
        return self.remote_version
    def handle_client_call(self, path, args, kwargs):
        if hasattr(self, path):
            # this is something implemented locally
            return getattr(self, path)(*args, **kwargs)
        else:
            # this is a remote api call
            return self.do_remote_api_call(path, args, kwargs)
    def do_remote_api_call(self, path, args, kwargs):
        # send the api call
        self.api_channel.write('API_CALL', path, args, kwargs)
        # wait for the result
        return self.wait_api_result()
    def handle_api_call(self, path, args, kwargs):
        res = self.local_api_handler.do(path, args, kwargs)
        self.api_channel.write('RESULT', res)
    def wait_api_result(self):
        self.indicator.start()
        api_result = None
        while True:
            self.indicator.update()
            timeout = MAX_BLOCKING_TIME
            r, w, e = select((self.sock,), (), (self.sock,), timeout)
            if len(e) > 0:  # if error
                break
            if len(r) == 0: # if timeout
                continue
            # otherwise, there is something to process on the api connection
            self.indicator.reset()  # apparently the server is no longer busy
            event = self.api_channel.read()
            if event != None:
                if event[0] == 'API_CALL':
                    self.handle_api_call(*event[1:])
                    continue
                elif event[0] == 'EXCEPTION':
                    print 'Unexpected server-side issue! %s' % event[1]
                    break
                elif event[0] == 'RESULT':
                    api_result = event[1]
                    break
            raise LinkException('Unexpected communication issue with the server.')
        self.indicator.done()
        return api_result
    def __del__(self):
        self.sock.close()

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
        self.conn.connect()
        return self.conn.client_proxy
    def __exit__(self, type, value, traceback):
        # do not close the connection right now, it might be reused
        # thanks to the @reusable decorator of ServerAPIConnection
        pass

