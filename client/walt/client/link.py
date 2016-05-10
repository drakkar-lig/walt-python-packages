#!/usr/bin/env python
import rpyc, os, sys, signal, threading
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.versions import API_VERSIONING
from walt.client.config import conf
from walt.client.filesystem import Filesystem
from multiprocessing import Queue
from walt.common.api import api, api_expose

@api
class ResponseQueue(object):
    def __init__(self):
        self.q = Queue()
    @api_expose
    def put(self, *args, **kwargs):
        self.q.put(*args, **kwargs)
    @api_expose
    def done(self):
        self.q.put(None)
    def get(self):
        return self.q.get()
    def wait(self):
        self.q.get()

@api
class ExposedStream(object):
    def __init__(self, stream):
        self.stream = stream
    @api_expose
    def fileno(self):
        return self.stream.fileno()
    @api_expose
    def readline(self, size=-1):
        return self.stream.readline(size)
    @api_expose
    def write(self, s):
        self.stream.write(s)
    @api_expose
    def flush(self):
        self.stream.flush()

# most of the functionality is provided at the server,
# of course. 
# but the client also exposes a few objects / features
# in the following class.
class WaltClientService(rpyc.Service):
    def __init__(self, *args, **kwargs):
        rpyc.Service.__init__(self, *args, **kwargs)
        self.exposed_stdin = ExposedStream(sys.stdin)
        self.exposed_stdout = ExposedStream(sys.stdout)
        self.exposed_stderr = ExposedStream(sys.stderr)
        self.exposed_username = conf['username']
        self.exposed_filesystem = Filesystem()

# in some cases we need a background thread that will handle
# RPyC events.
class BgRPyCThread(object):
    def __init__(self, conn):
        self.conn = conn
        self.thread = threading.Thread(target = self._bg_server)
        self.thread.setDaemon(True)
        self.active = True
        self.thread.start()
    def __del__(self):
        if self.active:
            self.stop()
    def _bg_server(self):
        try:
            while self.active:
                self.conn.serve()
        except Exception:
            if self.active:
                raise
    def stop(self):
        assert self.active
        self.active = False
        self.thread.join()
        self.conn = None

class ClientToServerLink:
    def __init__(self, bg_thread_enabled = False):
        self.bg_thread_enabled = bg_thread_enabled

    def __enter__(self):
        self.conn = rpyc.connect(
                conf['server'],
                WALT_SERVER_DAEMON_PORT,
                service = WaltClientService)
        if self.bg_thread_enabled:
            self.bg_thread = BgRPyCThread(self.conn)
        return self.conn.root

    def __exit__(self, type, value, traceback):
        if self.bg_thread_enabled:
            self.bg_thread.stop()
        self.conn.close()

def check_server_compatibility():
    with ClientToServerLink() as server:
        server_API_ser, server_API_cli = server.get_API()
        client_API_ser, client_API_cli = API_VERSIONING['SERVER'][0], API_VERSIONING['CLIENT'][0]
        if (server_API_ser, server_API_cli) != (client_API_ser, client_API_cli):
            print('Please change your client version using:')
            print('sudo pip install --upgrade "walt-client-selector==%d.%d.*"' % \
                            (server_API_ser, server_API_cli))
            return False
    return True
