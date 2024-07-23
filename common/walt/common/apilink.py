#!/usr/bin/env python
import sys
from socket import IPPROTO_TCP, TCP_NODELAY, create_connection
from time import time

from walt.common.api import api, api_expose_method
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.reusable import reusable
from walt.common.tcp import Requests, RWSocketFile, MyPickle as pickle
from walt.common.tools import BusyIndicator

SERVER_SOCKET_TIMEOUT = 10.0
SERVER_SOCKET_REUSE_TIMEOUT = 5.0


# This class is used both on the client and on the server.
# It should be backward-compatible with the "line-repr-eval"
# mode, in order to communicate with legacy code using it.
class APIChannel(object):
    def __init__(self, sock_file):
        self.sock_file = sock_file
        self.mode = "line-repr-eval"  # default mode

    def write(self, *args):
        if self.sock_file.closed:
            return
        if self.mode == "line-repr-eval":
            self.sock_file.write(repr(args).encode("UTF-8") + b"\n")
        elif self.mode == "pickle4":
            pickle.dump(args, self.sock_file, protocol=4)

    def read(self):
        if self.sock_file.closed:
            return None
        if self.mode == "line-repr-eval":
            return eval(self.sock_file.readline().decode("UTF-8"))
        elif self.mode == "pickle4":
            return pickle.load(self.sock_file)

    def fileno(self):
        return self.sock_file.fileno()

    def get_mode(self):
        return self.mode

    def set_mode(self, mode):
        if mode in ("pickle4", "line-repr-eval"):
            if isinstance(self.sock_file, RWSocketFile):
                pickle_mode = (mode=="pickle4")
                self.sock_file.pickle_mode = pickle_mode
            self.mode = mode
        else:
            raise Exception(f"Unknown APIChannel mode: {mode}")


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
    def __init__(self, handler, path=""):
        self.path = path
        self.handler = handler

    def __getattr__(self, attr):
        return AttrCallAggregator(self.handler, f"{self.path}.{attr}")

    def __getitem__(self, idx):
        return AttrCallAggregator(self.handler, f"{self.path}[{repr(idx)}]")

    def __call__(self, *args, **kwargs):
        return self.handler(self.path[1:], args, kwargs)


class AttrCallRunner(object):
    def __init__(self, handler):
        self.handler = handler

    def do(self, path, args, kwargs):
        obj = self.handler
        for attr in path.split("."):
            if "[" in attr:
                attr, rest = attr.split("[", maxsplit=1)
                subs = rest[:-1]
                obj = getattr(obj, attr)
                obj = obj[eval(subs)]
            else:
                obj = getattr(obj, attr)
        return obj(*args, **kwargs)


# Sometimes we start a long running process on the server and wait for
# its completion. In this case, while we are waiting, the server may
# send api calls to update the client stdout or stderr.
# This object provide methods to wait() and still be able to accept
# these calls.
MAX_BLOCKING_TIME = 0.1


class LinkException(Exception):
    pass


@reusable
class ServerAPIConnection(object):
    def __init__(self, server_ip, local_service, target_api, busy_indicator):
        if local_service is None:
            local_service = BaseAPIService()
        if busy_indicator is None:
            busy_indicator = BusyIndicator("Server is working")
        self.target_api = target_api
        self.server_ip = server_ip
        self.sock = None
        self.api_channel = None
        self.remote_version = None
        self.client_proxy = AttrCallAggregator(self.handle_client_call)
        self.local_api_handler = AttrCallRunner(local_service)
        self.local_service = local_service
        self.indicator = busy_indicator
        self.connected = False
        self.idle_start_time = None
        self.usage_refcount = 0  # might be > 1 in case of imbricated calls

    @property
    def in_use(self):
        return self.usage_refcount > 0

    # Since the object is reusable (see decorator above) we may reuse the connection.
    # When the reference counter reaches 0, we keep the connection open for
    # possible reuse up to SERVER_SOCKET_REUSE_TIMEOUT seconds.
    # After this time, next connection attempt will cause the socket to be closed
    # and re-opened (in order to avoid possible network issues with idle sockets
    # kept open too long). In API scripts, long idle server connection objects
    # is a usual pattern.
    def connect(self):
        if not self.in_use and self.connected:
            if time() - self.idle_start_time > SERVER_SOCKET_REUSE_TIMEOUT:
                # too old, disconnect
                # print('ServerAPILink.connect -- too old, disconnect')
                self.sock.close()
                self.sock = None
                self.connected = False
        self.usage_refcount += 1
        if not self.connected:
            # print('ServerAPILink.connect -- creating connection')
            try:
                # if the server hostname (or ip) contains only ASCII chars
                # we can prevent the socket.create_connection() function
                # from loading the IDNA encoding module and save a few milliseconds.
                server_ip = self.server_ip.encode('ascii')
                self.sock = self.create_connection(server_ip)
            except Exception:
                self.sock = self.create_connection(self.server_ip)
            self.sock.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)  # disable Nagle
            sock_file = RWSocketFile(self.sock)
            sock_file.write(
                b"%d\n%s\n"
                % (Requests.REQ_API_SESSION, self.target_api.encode("UTF-8"))
            )
            self.remote_version = sock_file.readline().strip().decode("UTF-8")
            self.api_channel = APIChannel(sock_file)
            # pickle4 is a faster mode for large transfers because line-repr-eval
            # uses readline() on the receiving side, which means reading chars one
            # by one up to the end of line. If the server is up-to-date, use it.
            if self.remote_has_pickle4_mode():
                self.api_channel.write("SET_MODE", 'pickle4')  # set mode remotely
                self.api_channel.set_mode('pickle4')           # set mode locally
            self.connected = True

    def create_connection(self, server_ip):
        return create_connection(
                (server_ip, WALT_SERVER_DAEMON_PORT),
                SERVER_SOCKET_TIMEOUT
        )

    def remote_has_pickle4_mode(self):
        if self.remote_version.startswith('0.'):  # dev version
            return True
        elif float(self.remote_version) >= 8.0:       # prod version
            return True
        else:
            return False

    def disconnect(self):
        self.usage_refcount -= 1
        if self.usage_refcount == 0:
            self.idle_start_time = time()

    def set_busy_label(self, label):
        # save info as local variables
        indicator = self.indicator
        prev_label = indicator.get_label()
        # set the label
        self.indicator.set_label(label)

        # propose a context manager for optional use in a 'with' context
        class BusyLabelRestorer:
            def __enter__(self):
                pass

            def __exit__(self, exc_type, exc_value, traceback):
                indicator.set_label(prev_label)

        return BusyLabelRestorer()

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
        self.api_channel.write("API_CALL", path, args, kwargs)
        # wait for the result
        return self.wait_api_result()

    def handle_api_call(self, path, args, kwargs):
        res = self.local_api_handler.do(path, args, kwargs)
        self.api_channel.write("RESULT", res)

    def wait_api_result(self):
        from select import select
        self.indicator.start()
        api_result = None
        while True:
            self.indicator.update()
            timeout = MAX_BLOCKING_TIME
            r, w, e = select((self.sock,), (), (self.sock,), timeout)
            if len(e) > 0:  # if error
                break
            if len(r) == 0:  # if timeout
                continue
            # otherwise, there is something to process on the api connection
            # handle_api_call() may cause something to be printed on our
            # stdout, so let's temporarily erase the busy indicator message
            self.indicator.reset()
            try:
                event = self.api_channel.read()
            except Exception as e:
                print(e)
                event = None
            if event is not None:
                if event[0] == "API_CALL":
                    self.handle_api_call(*event[1:])
                    continue
                elif event[0] == "EXCEPTION":
                    sys.exit("Unexpected server-side issue! %s" % event[1])
                elif event[0] == "RESULT":
                    api_result = event[1]
                    break
            raise LinkException("Unexpected communication issue with the server.")
        self.indicator.done()
        return api_result

    def set_config(self, **config):
        self.local_service.set_config(**config)

    def __del__(self):
        if self.sock is not None:
            self.sock.close()


@api
class BaseAPIService(object):
    def __init__(self):
        self.client_type = "cli"

    def set_config(self, client_type=None):
        if client_type is not None:
            self.client_type = client_type

    @api_expose_method
    def is_alive(self):
        return True

    @api_expose_method
    def get_client_type(self):
        return self.client_type


# This class provides a 'with' environment to connect to
# the server API.
class ServerAPILink(object):
    def __init__(self, server_ip, target_api, local_service=None, busy_indicator=None):
        self.conn = ServerAPIConnection(
            server_ip, local_service, target_api, busy_indicator
        )

    def __enter__(self):
        # print('ServerAPILink.__enter__')
        self.conn.connect()
        # print(f'self.conn: {self.conn}')
        # print(f'self.conn.sock: {self.conn.sock} <- same object if repeating < 5s')
        return self.conn.client_proxy

    def __exit__(self, type, value, traceback):
        # print('ServerAPILink.__exit__')
        self.conn.disconnect()

    def set_busy_label(self, label):
        self.conn.set_busy_label(label)

    def set_default_busy_label(self):
        self.conn.set_default_busy_label()
