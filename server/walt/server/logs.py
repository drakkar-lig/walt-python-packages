import socket
from datetime import datetime
from walt.common.tcp import read_pickle, write_pickle, \
                            Requests

class LogsToDBHandler(object):
    def __init__(self, db):
        self.db = db

    def log(self, **record):
        self.db.insert('logs', **record)

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
    def handle_event(self, ts):
        if self.stream_id == None:
            self.stream_id = self.register_new_stream()
            # register_new_stream() involves a read on the stream
            # to get its name.
            # supposedly that's why we have been woken up.
            # let the event loop call us again if there is more.
            return True
        record = read_pickle(self.sock_file)
        if record == None:
            print 'Log stream with id %d is being closed.' % self.stream_id
            # let the event loop know we should 
            # be removed.
            return False
        # convert timestamp to datetime
        ts = record['timestamp']
        if not isinstance(ts, datetime):
            record['timestamp'] = datetime.fromtimestamp(ts)
        record.update(stream_id=self.stream_id)
        self.hub.log(**record)
        return True
    def close(self):
        self.sock_file.close()

class RetrieveDBLogsTask(object):
    def __init__(self, client_handler):
        self.handler = client_handler
        self.db = self.handler.db
    def prepare(self):
        # ensure all past logs are commited
        self.db.commit()
        # create a server cursor
        self.c = self.db.get_server_cursor()
    def perform(self):
        # this is where things may take some time...
        for record in self.db.get_logs(self.c, **self.handler.params):
            d = record._asdict()
            if self.handler.write_to_client(**d) == False:
                break
        del self.c
    def handle_result(self, res):
        self.handler.notify_history_processed()

class LogsToSocketHandler(object):
    def __init__(self, db, hub, sock, sock_file, blocking, **kwargs):
        self.db = db
        self.db_logs_task = RetrieveDBLogsTask(self)
        self.sock_file_r = sock_file
        self.sock_file_w = sock.makefile('w', 0)
        self.cache = {}
        self.params = None
        self.hub = hub
        self.blocking = blocking
        self.retrieving_from_db = None
        self.realtime_buffer = []
        #sock.settimeout(1.0)
    def log(self, **record):
        # if we are processing the history part,
        # do not send the realtime logs right now
        if self.retrieving_from_db:
            self.realtime_buffer.append(record)
        else:   # ok, write to client
            return self.write_to_client(**record)
    def notify_history_processed(self):
        if self.params['realtime']:
            # done with the history part.
            # we can flush the buffer of realtime logs
            for record in self.realtime_buffer:
                if self.write_to_client(**record) == False:
                    break
            # notify that next logs can be sent
            # directly to the client
            self.retrieving_from_db = False
        else:
            # no realtime mode, we can quit
            self.close()
    def write_to_client(self, stream_id, **record):
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
            if self.sock_file_w.closed:
                raise IOError()
            write_pickle(d, self.sock_file_w)
        except IOError as e:
            # the socket was supposedly closed.
            print "client log connection closing"
            # notify the hub that we should be removed.
            return False
    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file_r.fileno()
    # this is what we will do depending on the client request params
    def handle_params(self):
        history = self.params['history']
        realtime = self.params['realtime']
        if history:
            self.retrieving_from_db = True
            self.db_logs_task.prepare()
            self.blocking.do(self.db_logs_task)
        else:
            self.retrieving_from_db = False
        if realtime:
            self.hub.addHandler(self)
    # this is what we do when the event loop detects an event for us
    def handle_event(self, ts):
        if self.params == None:
            self.params = read_pickle(self.sock_file_r)
            self.handle_params()
        else:
            return False    # no more communication is expected this way
    def close(self):
        self.sock_file_r.close()
        self.sock_file_w.close()

class LogsManager(object):
    def __init__(self, db, tcp_server, blocking):
        self.db = db
        self.blocking = blocking
        self.hub = LogsHub()
        self.hub.addHandler(LogsToDBHandler(db))
        tcp_server.register_listener_class(
                    req_id = Requests.REQ_DUMP_LOGS,
                    cls = LogsToSocketHandler,
                    db = self.db,
                    hub = self.hub,
                    blocking = self.blocking)
        tcp_server.register_listener_class(
                    req_id = Requests.REQ_NEW_INCOMING_LOGS,
                    cls = LogsStreamListener,
                    db = self.db,
                    hub = self.hub)
