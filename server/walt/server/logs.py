import socket
from walt.common.constants import WALT_SERVER_LOGS_PORT
from walt.common.logs import *

class LogsToDBHandler(object):
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
        to_be_removed = set([])
        for handler in self.handlers:
            res = handler.log(**kwargs)
            # a handler may request to be deleted
            # by returning False
            if res == False:
                to_be_removed.add(handler)
        for handler in to_be_removed:
            self.handlers.remove(handler)

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
            record = read_encoded_from_log_stream(self.sock_file)
        except Exception as e:
            print 'Log stream with id %d is being closed.' % self.stream_id
            # let the event loop know we should 
            # be removed.
            return False
        self.hub.log(record=record, stream_id=self.stream_id)
        return True
    def close(self):
        self.sock_file.close()

class LogsTCPServer(object):
    def __init__(self, db, hub):
        self.init_server_socket()
        self.db = db
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
            req_type, req_data = read_encoded_from_log_stream(sock_file)
        except Exception as e:
            print e
            print 'Invalid log request.'
            return
        if req_type == REQ_NEW_INCOMING_LOGS:
            stream_id = self.register_new_stream(conn_s, req_data)
            print 'New log stream with id %d.' % stream_id
            stream_listener = LogsStreamListener(
                        sock_file, stream_id, self.hub)
            self.ev_loop.register_listener(stream_listener)
        elif req_type == REQ_DUMP_LOGS:
            self.hub.addHandler(LogsToSocketHandler(self.db, sock_file))

    def register_new_stream(self, sock, name):
        sender_ip, sender_port = sock.getpeername()
        sender_info = self.db.select_unique('devices', ip = sender_ip)
        if sender_info == None:
            sender_mac = None
        else:
            sender_mac = sender_info['mac']
        self.db.insert('logstreams', sender_mac = sender_mac, name = name)
        stream_id = self.db.lastrowid
        return stream_id

    def close(self):
        self.s.close()

class LogsToSocketHandler(object):
    def __init__(self, db, sock_file):
        self.db = db
        self.sock_file = sock_file
        self.cache = {}

    def log(self, record, stream_id):
        try:
            if stream_id not in self.cache:
                self.cache[stream_id] = self.db.execute(
                """SELECT d.name as sender, s.name as stream
                   FROM logstreams s, devices d
                   WHERE s.id = %s
                     AND s.sender_mac = d.mac
                """ % stream_id).fetchall()[0]
            d = {}
            d.update(record)
            d.update(self.cache[stream_id])
            write_encoded_to_log_stream(d, self.sock_file)
        except Exception as e:
            # the socket was supposedly closed.
            # notify the hub that we should be removed.
            return False

class LogsManager(object):
    def __init__(self, db, ev_loop):
        self.db = db
        self.hub = LogsHub()
        self.hub.addHandler(LogsToDBHandler(db))
        self.tcp_server = LogsTCPServer(db, self.hub)
        self.tcp_server.join_event_loop(ev_loop)

