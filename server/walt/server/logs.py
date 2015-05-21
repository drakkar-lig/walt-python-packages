import socket, cPickle as pickle
from walt.common.constants import WALT_SERVER_LOGS_PORT

class LogsDBHandler(object):
    def __init__(self, db):
        self.db = db

    def log(self, record, stream_id):
        self.db.insert('logs',
                stream_id = stream_id,
                **record)

class LogsHub(object):
    def __init__(self):
        self.handlers = set([])

    def addHandler(self, handler):
        self.handlers.add(handler)

    def removeHandler(self, handler):
        self.handlers.remove(handler)

    def log(self, **kwargs):
        for handler in self.handlers:
            handler.log(**kwargs)

class LogsStreamListener(object):
    def __init__(self, sock_file, stream_id, hub):
        self.sock_file = sock_file
        self.stream_id = stream_id
        self.hub = hub
    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file.fileno()
    # when the event loop detects an event for us, we
    # know a log line should be read. 
    def handle_event(self):
        try:
            record = pickle.load(self.sock_file)
        except Exception as e:
            print e
            print 'Client log connection will be closed.'
            # let the event loop know we should 
            # be removed.
            return False
        self.hub.log(record=record, stream_id=self.stream_id)
        return True
    def close(self):
        self.sock_file.close()

class LogsTCPServer(object):
    def __init__(self, hub):
        self.init_server_socket()
        self.hub = hub

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)

    def init_server_socket(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', WALT_SERVER_LOGS_PORT))
        s.listen(1)
        self.s = s

    # let the event loop know what we are reading on
    def fileno(self):
        return self.s.fileno()

    # when the event loop detects an event for us, this is 
    # what we will do: accept the tcp connection, create
    # a stream listener that will register the logs coming
    # from there, and register this listener in the event
    # loop.
    def handle_event(self):
        conn_s, addr = self.s.accept()
        sock_file = conn_s.makefile()
        try:
            stream_id = pickle.load(sock_file)
            print 'New log connection: stream_id %d' % stream_id
            stream_listener = LogsStreamListener(
                        sock_file, stream_id, self.hub)
            self.ev_loop.register_listener(stream_listener)
        except:
            print 'Invalid stream_id in new log connection.'
        finally:
            # whatever happens, we continue our job in the event 
            # loop (i.e. waiting for new connections)
            return True

    def close(self):
        self.s.close()

class LogsManager(object):
    def __init__(self, db, ev_loop):
        self.db = db
        self.hub = LogsHub()
        self.hub.addHandler(LogsDBHandler(db))
        self.tcp_server = LogsTCPServer(self.hub)
        self.tcp_server.join_event_loop(ev_loop)

    def create_new_stream(self, sender_mac, name):
        self.db.insert('logstreams', sender_mac = sender_mac, name = name)
        stream_id = self.db.lastrowid
        return stream_id

