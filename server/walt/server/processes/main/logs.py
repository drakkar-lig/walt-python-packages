import re, pickle, sys
from datetime import datetime
from walt.common.constants import WALT_SERVER_NETCONSOLE_PORT
from walt.common.tcp import read_pickle, write_pickle, \
                            Requests, PICKLE_VERSION
from walt.common.udp import udp_server_socket
from walt.server.tools import get_server_ip

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
    def __init__(self, manager, sock_file, **kwargs):
        self.manager = manager
        self.hub = manager.hub
        self.sock_file = sock_file
        self.stream_id = None
        self.server_timestamps = None

    def register_stream(self):
        name = self.sock_file.readline().strip().decode('UTF-8')
        timestamps_mode = self.sock_file.readline().strip()
        self.server_timestamps = (timestamps_mode == b'NO_TIMESTAMPS')
        sender_ip, sender_port = self.sock_file.getpeername()
        return self.manager.get_stream_id(sender_ip, name)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file.fileno()
    # when the event loop detects an event for us, we
    # know a log line should be read.
    def handle_event(self, ts):
        if self.stream_id == None:
            self.stream_id = self.register_stream()
            if self.stream_id is None:
                return False
            # register_stream() involves a read on the stream
            # to get its name.
            # supposedly that's why we have been woken up.
            # let the event loop call us again if there is more.
            return True
        try:
            inputline = self.sock_file.readline().strip().decode('UTF-8')
            if inputline == 'CLOSE':
                return False    # stop here
            if self.server_timestamps:
                line = inputline
                timestamp = ts
            else:
                timestamp, line = inputline.split(None, 1)
                timestamp = float(timestamp)
            record = dict(
                timestamp = timestamp,
                line = line)
        except BaseException as e:
            print(e)
            print('Log stream with id %d is being closed.' % self.stream_id)
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

class FileListener:
    """Listens for chunks output by given file and save them as logs."""
    def __init__(self, hub, fileobj, stream_id):
        self.hub = hub
        self.file = fileobj
        self.stream_id = stream_id

    def fileno(self):
        return self.file.fileno()

    def handle_event(self, ts):
        try:
            chunk = self.file.read(4096)
            if len(chunk) == 0:
                return False
        except:
            return False
        timestamp = ts
        if not isinstance(timestamp, datetime):
            timestamp = datetime.fromtimestamp(timestamp)
        record = dict(timestamp=timestamp, line=repr(chunk), stream_id=self.stream_id)
        self.hub.log(**record)
        return True

    def close(self):
        self.file.close()

class NetconsoleListener(object):
    """Listens for netconsole messages sent by nodes over UDP, and store
    them as regular logs."""
    def __init__(self, manager, port, **kwargs):
        self.manager = manager
        self.hub = manager.hub
        self.s = udp_server_socket(port)
        self.sender_info = dict()

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.s.fileno()

    def handle_event(self, ts):
        # TODO: we should decode the extended format and handle continuation messages.
        # https://www.kernel.org/doc/Documentation/ABI/testing/dev-kmsg
        (msg, addrinfo) = self.s.recvfrom(9000)
        sender_ip, sender_port = addrinfo
        if sender_ip not in self.sender_info:
            # Cache IP -> stream ID association, to avoid hitting the
            # database for each received netconsole message.
            stream_id = self.manager.get_stream_id(sender_ip, 'netconsole')
            if stream_id is None:
                # ignore this UDP message, but obviously continue listening
                return True
            # Second list element is the current pending message for this sender
            # (in some cases we may receive a line in multiple parts before getting
            # the end-of-line char)
            self.sender_info[sender_ip] = [stream_id, b'']
        stream_id, cur_msg = self.sender_info[sender_ip]
        cur_msg += msg
        # log terminated lines
        lines = cur_msg.split(b'\n')
        if len(lines) > 1:
            timestamp = ts
            if not isinstance(timestamp, datetime):
                timestamp = datetime.fromtimestamp(timestamp)
            for line in lines[:-1]: # terminated lines
                record = dict(timestamp=timestamp, line=line.decode('ascii'), stream_id=stream_id)
                self.hub.log(**record)
        # update current message of this sender
        cur_msg = lines[-1] # last line (unterminated one)
        self.sender_info[sender_ip][1] = cur_msg
        return True

    def forget_ip(self, device_ip):
        if device_ip in self.sender_info:
            del self.sender_info[device_ip]

    def close(self):
        self.s.close()

PHASE_WAIT_FOR_BLCK_THREAD = 0
PHASE_RETRIEVING_FROM_DB = 1
PHASE_SENDING_TO_CLIENT = 2
class LogsToSocketHandler(object):
    def __init__(self, manager, sock_file, **kwargs):
        self.manager = manager
        self.sock_file = sock_file
        self.cache = {}
        self.params = None
        self.hub = manager.hub
        self.blocking = manager.blocking
        self.phase = None
        self.realtime_buffer = []
        #sock.settimeout(1.0)
    def log(self, **record):
        if self.phase == PHASE_WAIT_FOR_BLCK_THREAD:
            # blocking process is not ready yet,
            # we will let the log go to db and
            # the blocking process will retrieve it later.
            return
        elif self.phase == PHASE_RETRIEVING_FROM_DB:
            # the blocking process is still sending logs
            # from db
            # => do not send the realtime logs right now,
            # record them for later
            self.realtime_buffer.append(record)
        elif self.phase == PHASE_SENDING_TO_CLIENT:
            return self.write_to_client(**record)
    def notify_history_processing_startup(self):
        self.phase = PHASE_RETRIEVING_FROM_DB
    def notify_history_processed(self):
        if self.params['realtime']:
            # done with the history part.
            # we can flush the buffer of realtime logs
            for record in self.realtime_buffer:
                if self.write_to_client(**record) == False:
                    break
            # notify that next logs can be sent
            # directly to the client
            self.phase = PHASE_SENDING_TO_CLIENT
        else:
            # no realtime mode, we can quit
            self.close()
    def write_to_client(self, stream_id, senders_filtered=False, **record):
        try:
            if stream_id not in self.cache:
                self.cache[stream_id] = self.manager.get_stream_info(stream_id)
            stream_info = self.cache[stream_id]
            # when data comes from the db, senders are already filtered,
            # while data coming from the hub has to be filtered.
            if not senders_filtered:
                if stream_info['sender'] not in self.params['senders']:
                    return  # filter out
            # matching the streams or the logline is always done here, otherwise
            # there may be inconsistencies between the regexp format in the
            # postgresql database and in python
            if self.streams_regexp:
                matches = self.streams_regexp.findall(stream_info['stream'])
                if len(matches) == 0:
                    return  # filter out
            if self.logline_regexp:
                matches = self.logline_regexp.findall(record['line'])
                if len(matches) == 0:
                    return  # filter out
            d = {}
            d.update(record)
            d.update(stream_info)
            if self.sock_file.closed:
                raise IOError()
            write_pickle(d, self.sock_file)
        except IOError as e:
            # the socket was supposedly closed.
            print("client log connection closing")
            # notify the hub that we should be removed.
            return False
    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file.fileno()
    # this is what we will do depending on the client request params
    def handle_params(self, history, realtime, senders, streams, logline_regexp):
        if history:
            # unpickle the elements of the history range
            history = tuple(pickle.loads(e) if e else None for e in history)
        if streams:
            self.streams_regexp = re.compile(streams)
        else:
            self.streams_regexp = None
        if logline_regexp:
            self.logline_regexp = re.compile(logline_regexp)
        else:
            self.logline_regexp = None
        self.params = dict( history = history,
                            realtime = realtime,
                            senders = senders)
        if history:
            self.phase = PHASE_WAIT_FOR_BLCK_THREAD
            self.blocking.stream_db_logs(self)
        else:
            self.phase = PHASE_SENDING_TO_CLIENT
        if realtime:
            self.hub.addHandler(self)
    # this is what we do when the event loop detects an event for us
    def handle_event(self, ts):
        if self.params == None:
            params = read_pickle(self.sock_file)
            self.handle_params(**params)
        else:
            return False    # no more communication is expected this way
    def close(self):
        self.sock_file.close()

class LoggerFile:
    def __init__(self, logs_manager, stream_name, secondary_file):
        self.logs_manager = logs_manager
        self.stream_name = stream_name
        self.secondary_file = secondary_file
        self.buffer = ''
        self._flushing = False
    def write(self, s):
        self.secondary_file.write(s)
        self.buffer += s
        # avoid recursive calls while flushing
        if self._flushing:
            return
        self.do_flush()
    def do_flush(self):
        self._flushing = True
        while True:
            parts = self.buffer.split('\n')
            if len(parts) == 1:
                break
            self.buffer = parts[-1]
            for line in parts[:-1]:
                if '__DEBUG__' not in line:
                    self.logs_manager.server_log(self.stream_name, line)
        self._flushing = False
    def flush(self):
        self.secondary_file.flush()
    def fileno(self):
        return self.secondary_file.fileno()
    @property
    def encoding(self):
        return self.secondary_file.encoding

class LogsManager(object):
    def __init__(self, db, tcp_server, blocking, ev_loop):
        self.ev_loop = ev_loop
        self.db = db
        self.server_ip = get_server_ip()
        self.blocking = blocking
        self.server_log_cache = {}
        self.hub = LogsHub()
        self.hub.addHandler(LogsToDBHandler(db))
        tcp_server.register_listener_class(
                    req_id = Requests.REQ_DUMP_LOGS,
                    cls = LogsToSocketHandler,
                    manager = self)
        tcp_server.register_listener_class(
                    req_id = Requests.REQ_NEW_INCOMING_LOGS,
                    cls = LogsStreamListener,
                    manager = self)
        self.netconsole = NetconsoleListener(self, WALT_SERVER_NETCONSOLE_PORT)
        self.netconsole.join_event_loop(ev_loop)

    def monitor_file(self, fileobj, sender_ip, stream_name):
        stream_id = self.get_stream_id(sender_ip, stream_name, 'chunk')
        listener = FileListener(self.hub, fileobj, stream_id)
        self.ev_loop.register_listener(listener)
        return listener

    def catch_std_streams(self):
        sys.stdout = LoggerFile(self, 'daemon.stdout', sys.__stdout__)
        sys.stderr = LoggerFile(self, 'daemon.stderr', sys.__stderr__)

    def get_stream_id(self, sender_ip, stream_name, mode='line'):
        sender_info = self.db.select_unique('devices', ip = sender_ip)
        if sender_info == None:
            # sender device is unknown in database,
            # this stream must be ignored
            return None
        sender_mac = sender_info.mac
        stream_info = self.db.select_unique('logstreams',
                            sender_mac = sender_mac, name = stream_name)
        if stream_info:
            # found existing stream
            stream_id = stream_info.id
        else:
            # register new stream
            stream_id = self.db.insert('logstreams', returning='id',
                            sender_mac = sender_mac, name = stream_name,
                            mode = mode)
        return stream_id

    def get_stream_info(self, stream_id):
        return self.db.execute(
                """SELECT d.name as sender, s.name as stream
                   FROM logstreams s, devices d
                   WHERE s.id = %s
                     AND s.sender_mac = d.mac
                """ % stream_id)[0]._asdict()

    def platform_log(self, stream_name, line):
        self.server_log('platform.' + stream_name, line)

    def server_log(self, stream_name, line):
        if stream_name not in self.server_log_cache:
            self.server_log_cache[stream_name] = \
                    self.get_stream_id(self.server_ip, stream_name)
        stream_id = self.server_log_cache[stream_name]
        self.hub.log(timestamp = datetime.now(),
                     line = line,
                     stream_id = stream_id)

    def forget_device(self, device_name):
        device_info = self.db.select_unique('devices', name=device_name)
        self.netconsole.forget_ip(device_info.ip)

    # Look for a checkpoint. Return a tuple.
    # If the result conforms to 'expected', return (True, <checkpoint_found_or_none>)
    # If not or an issue occured, return (False,)
    def get_checkpoint(self, requester, cp_name, expected=True):
        username = requester.get_username()
        if not username:
            return (False,)    # client already disconnected, give up
        cp_info = self.db.select_unique(
            'checkpoints', name=cp_name, username=requester.get_username())
        if expected and cp_info == None:
            requester.stderr.write("Failed: no checkpoint with this name '%s'.\n" % cp_name)
            return (False,)
        if not expected and cp_info != None:
            requester.stderr.write('Failed: a checkpoint with this name already exists.\n')
            return (False,)
        return (True, cp_info)

    def add_checkpoint(self, requester, cp_name, date):
        # expect no existing checkpoint with the same name
        if not self.get_checkpoint(requester, cp_name, expected=False)[0]:
            return
        if not date:
            date = datetime.now()
        self.db.insert('checkpoints',
                name=cp_name, username=requester.get_username(), timestamp=date)
        requester.stdout.write("New checkpoint %s recorded at server time: %s.\n" % (cp_name, date))

    def remove_checkpoint(self, requester, cp_name):
        # expect a checkpoint with this name
        if not self.get_checkpoint(requester, cp_name, expected=True)[0]:
            return
        self.db.delete('checkpoints', name=cp_name, username=requester.get_username())
        requester.stdout.write("Done.\n")

    def list_checkpoints(self, requester):
        username = requester.get_username()
        if not username:
            return None    # client already disconnected, give up
        res = self.db.select('checkpoints', username=username)
        if len(res) == 0:
            requester.stdout.write('You own no checkpoints.\n')
        else:
            # re-execute because we don't want the 'username' column.
            requester.stdout.write(
                self.db.pretty_printed_select("""
                    SELECT timestamp, name FROM checkpoints
                    WHERE username = %s;
            """, (username,)) + '\n')

    def get_pickled_checkpoint_time(self, requester, cp_name):
        res = self.get_checkpoint(requester, cp_name, expected=True)
        if not res[0]:
            return
        cp_info = res[1]
        return pickle.dumps(cp_info.timestamp, protocol=PICKLE_VERSION)

