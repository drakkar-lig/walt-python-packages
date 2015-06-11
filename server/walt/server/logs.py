import socket
from walt.common.tcp import read_pickle, write_pickle, \
                            REQ_NEW_INCOMING_LOGS, REQ_DUMP_LOGS

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
    def __init__(self, db, hub, sock, sock_file, **kwargs):
        self.db = db
        self.hub = hub
        self.sock = sock
        self.sock_file = sock_file
        self.stream_id = None

    def register_new_stream(self):
        name = str(read_pickle(self.sock_file))
        sender_ip, sender_port = self.sock.getpeername()
        sender_info = self.db.select_unique('devices', ip = sender_ip)
        if sender_info == None:
            sender_mac = None
        else:
            sender_mac = sender_info.mac
        stream_id = self.db.insert('logstreams', returning='id',
                            sender_mac = sender_mac, name = name)
        # these are not needed anymore
        self.db = None
        self.sock = None
        return stream_id

    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file.fileno()
    # when the event loop detects an event for us, we
    # know a log line should be read. 
    def handle_event(self):
        if self.stream_id == None:
            self.stream_id = self.register_new_stream()
        record = read_pickle(self.sock_file)
        if record == None:
            print 'Log stream with id %d is being closed.' % self.stream_id
            # let the event loop know we should 
            # be removed.
            return False
        self.hub.log(record=record, stream_id=self.stream_id)
        return True
    def close(self):
        self.sock_file.close()

class LogsToSocketHandler(object):
    def __init__(self, db, hub, sock_file, **kwargs):
        self.db = db
        self.sock_file = sock_file
        self.cache = {}
        hub.addHandler(self)
    def log(self, record, stream_id):
        try:
            if stream_id not in self.cache:
                self.cache[stream_id] = self.db.execute(
                """SELECT d.name as sender, s.name as stream
                   FROM logstreams s, devices d
                   WHERE s.id = %s
                     AND s.sender_mac = d.mac
                """ % stream_id).fetchall()[0]._asdict()
            d = {}
            d.update(record)
            d.update(self.cache[stream_id])
            write_pickle(d, self.sock_file)
        except Exception as e:
            print e
            # the socket was supposedly closed.
            # notify the hub that we should be removed.
            return False
    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file.fileno()
    # this is what we do when the event loop detects an event for us
    def handle_event(self):
        return False    # no communication is expected this way
    def close(self):
        self.sock_file.close()

class LogsManager(object):
    def __init__(self, db, tcp_server):
        self.db = db
        self.hub = LogsHub()
        self.hub.addHandler(LogsToDBHandler(db))
        tcp_server.register_listener_class(
                    req_id = REQ_DUMP_LOGS,
                    cls = LogsToSocketHandler,
                    db = self.db,
                    hub = self.hub)
        tcp_server.register_listener_class(
                    req_id = REQ_NEW_INCOMING_LOGS,
                    cls = LogsStreamListener,
                    db = self.db,
                    hub = self.hub)
