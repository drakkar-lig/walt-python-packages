import json
import numpy as np
import re
import sys
from collections import defaultdict
from datetime import datetime
from numpy.lib.recfunctions import rec_join as np_rec_join
from time import time

from walt.common.constants import WALT_SERVER_NETCONSOLE_PORT
from walt.common.tcp import MyPickle as pickle, Requests, read_pickle, write_pickle
from walt.common.udp import udp_server_socket
from walt.server.regex import PosixExtendedRegex
from walt.server.tools import get_server_ip, np_recarray_to_tuple_of_dicts
from walt.server.processes.main.workflow import Workflow

TEN_YEARS = 3600 * 24 * 365 * 10
LOG_DT = [("timestamp", np.float64),
          ("line", object),
          ("stream_id", np.int32)]
CLIENT_LOG_DT = [("timestamp", object),
                 ("line", object),
                 ("issuer", object),
                 ("stream", object)]
LOG_PENDING_SIZE = 512
DB_LOGS_BLOCK_SIZE = 128


class LogsBuffer:
    def __init__(self, init_size):
        self._buffer = np.empty(init_size, LOG_DT)
        self.size = 0   # public attr for performance

    def append(self, logs):
        new_size = self.size + logs.size
        if new_size > self._buffer.size:
            self._buffer = np.append(self._buffer[:self.size], logs)
        else:
            self._buffer[self.size:new_size] = logs
        self.size = new_size

    def pop(self):
        size = self.size
        self.size = 0
        return self._buffer[:size].view(np.recarray)


class LogsToDBHandler(object):
    # Logs cause many inserts in db, so we buffer
    # them during a limited time and then possibly
    # insert many of them at once.
    BUFFERING_DELAY_SECS = 0.3

    def __init__(self, ev_loop, db):
        self.ev_loop = ev_loop
        self.db = db
        self.pending_records = LogsBuffer(2*LOG_PENDING_SIZE)

    def log(self, logs):
        self.pending_records.append(logs)
        # flush or plan flush
        if self.pending_records.size >= LOG_PENDING_SIZE:
            self.flush()
        elif self.pending_records.size == logs.size:
            self.ev_loop.plan_event(
                time() + LogsToDBHandler.BUFFERING_DELAY_SECS, callback=self.flush
            )

    def flush(self):
        if self.pending_records.size > 0:
            # we use an async call for not blocking, for better performance and
            # to avoid reentrance problems we could have with a sync call.
            self.db.do_async.insert_multiple_logs(self.pending_records.pop())


class LogsHub(object):
    def __init__(self):
        self.handlers = set([])

    def addHandler(self, handler):
        self.handlers.add(handler)

    def removeHandler(self, handler):
        self.handlers.remove(handler)

    def log(self, stream_id, line=None, lines=None,
            timestamp=None, timestamps=None, secondary_file=None):
        if lines is None:
            assert line is not None
            lines = np.array([line])
        if secondary_file is not None:
            block = np.add.reduce(lines.astype("O") + "\n")
            secondary_file.write(block)
        if timestamps is None:
            if timestamp is None:
                timestamp = time()
            timestamps = np.full(lines.size, timestamp)
        logs = np.empty(lines.size, LOG_DT).view(np.recarray)
        logs.timestamp, logs.line, logs.stream_id = timestamps, lines, stream_id
        for handler in self.handlers.copy():
            if handler not in self.handlers:
                continue
            res = handler.log(logs)
            # a handler may request to be deleted
            # by returning False
            if res is False and handler in self.handlers:
                self.handlers.remove(handler)


class LogsStreamListener(object):
    def __init__(self, manager, sock_file, **kwargs):
        self.manager = manager
        self.hub = manager.hub
        self.sock_file = sock_file
        self.stream_id = None
        self.server_timestamps = None
        self.chunk = ""

    def register_stream(self):
        name = self.sock_file.readline().strip().decode("UTF-8")
        timestamps_mode = self.sock_file.readline().strip()
        self.server_timestamps = timestamps_mode == b"NO_TIMESTAMPS"
        issuer_ip, issuer_port = self.sock_file.getpeername()
        return self.manager.get_stream_id(issuer_ip, name)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file.fileno()

    # when the event loop detects an event for us, we
    # know a log line should be read.
    def handle_event(self, ts):
        if self.stream_id is None:
            self.stream_id = self.register_stream()
            if self.stream_id is None:
                return False
            # register_stream() involves a read on the stream
            # to get its name.
            # supposedly that's why we have been woken up.
            # let the event loop call us again if there is more.
            return True
        try:
            should_continue = True
            new_chunk = self.sock_file.read()
            if len(new_chunk) == 0:
                # unexpected disconnection
                new_chunk = b"<disconnected!>\nCLOSE\n"
            self.chunk += new_chunk.decode("UTF-8")
            inputlines = np.array(self.chunk.split("\n"))
            if (inputlines[-2:] == ('CLOSE', '')).all():
                should_continue = False
                inputlines = inputlines[:-2]
            else:
                self.chunk = inputlines[-1]
                inputlines = inputlines[:-1]
            if inputlines.size > 0:
                if self.server_timestamps:
                    self.hub.log(self.stream_id, lines=inputlines, timestamp=ts)
                else:
                    partition = np.char.partition(inputlines, " ")
                    timestamps, lines = partition[:,0].astype(float), partition[:,2]
                    # detect wrong timestamps, replace with ts
                    mask = (timestamps < ts - TEN_YEARS) | (timestamps > ts + 1)
                    timestamps[mask] = ts
                    self.hub.log(self.stream_id, lines=lines, timestamps=timestamps)
            return should_continue
        except BaseException as e:
            print(e)
            print("Log stream with id %d is being closed." % self.stream_id)
            # let the event loop know we should
            # be removed.
            return False

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
        except Exception:
            return False
        self.hub.log(
            timestamp=ts, line=repr(chunk), stream_id=self.stream_id
        )
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
        self.issuer_info = dict()

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
        issuer_ip, issuer_port = addrinfo
        if issuer_ip not in self.issuer_info:
            # Cache IP -> stream ID association, to avoid hitting the
            # database for each received netconsole message.
            stream_id = self.manager.get_stream_id(issuer_ip, "netconsole")
            if stream_id is None:
                # ignore this UDP message, but obviously continue listening
                return True
            # Second list element is the current pending message for this issuer
            # (in some cases we may receive a line in multiple parts before getting
            # the end-of-line char)
            self.issuer_info[issuer_ip] = [stream_id, ""]
        stream_id, cur_msg = self.issuer_info[issuer_ip]
        cur_msg += msg.decode("utf8")
        # log terminated lines
        lines = np.array(cur_msg.split("\n"))
        if lines.size > 1:
            self.hub.log(stream_id, lines=lines[:-1], timestamp=ts)
        # update current message of this issuer
        cur_msg = lines[-1]  # last line (unterminated one)
        self.issuer_info[issuer_ip][1] = cur_msg
        return True

    def forget_ip(self, device_ip):
        if device_ip in self.issuer_info:
            del self.issuer_info[device_ip]

    def close(self):
        self.s.close()


PHASE_RETRIEVING_FROM_DB = 0
PHASE_SENDING_TO_CLIENT = 1


class LogsToSocketHandler(object):
    def __init__(self, manager, sock_file, **kwargs):
        self.manager = manager
        self.sock_file = sock_file
        dt_cache = [("stream_id", "O"), ("issuer", "O"), ("stream", "O")]
        self.cache = np.array([], dt_cache).view(np.recarray)
        self.db_params = None
        self.hub = manager.hub
        self.phase = None
        self.realtime_buffer = LogsBuffer(0)
        self.np_datetime_from_ts = np.vectorize(datetime.fromtimestamp)
        # sock.settimeout(1.0)

    def log(self, logs):
        if self.phase == PHASE_RETRIEVING_FROM_DB:
            # we are still sending logs from db
            # => do not send the realtime logs right now,
            # record them for later
            self.realtime_buffer.append(logs)
        elif self.phase == PHASE_SENDING_TO_CLIENT:
            return self.write_realtime_logs_to_client(logs)

    # important notes:
    # * when data comes from the db, then issuers, logline regexp and stream regexp
    #   are already filtered, but realtime logs have to be filtered.
    # * this implies that data is sometimes filtered by python, and sometimes by
    #   postgresql, so we need to agree on a common format for user-supplied
    #   regular expressions.
    # * default python regex format ("re" module) is not standard, so we use
    #   "walt.server.regex" iwhich is a cffi based interface to access extended
    #   posix regex features of libc.
    # * in postgresql queries (cf. db.py), we prefix regular expressions
    #   with "(?e)" in order to limit the format to extended posix regex too.
    def write_realtime_logs_to_client(self, logs):
        # check the logline regexp if defined
        if self.logline_re_match is not None:
            mask_lines = self.logline_re_match(logs.line)
            if not mask_lines.any():
                return  # all logs filtered out
            logs = logs[mask_lines]
        # analyse the streams found in those logs:
        # get issuer and stream name from cache, or from db if missing
        stream_ids, rev = np.unique(logs.stream_id, return_inverse=True)
        stream_info = np_rec_join("stream_id",
                                  stream_ids.astype([("stream_id", "O")]),
                                  self.cache, jointype="leftouter",
                                  defaults={"issuer": None, "stream": None})
        mask_cache_miss = (stream_info.issuer == None)
        if mask_cache_miss.any():
            # some stream info is missing from cache, query db
            db_stream_ids = stream_info[mask_cache_miss].stream_id
            db_res = self.manager.get_streams_info(db_stream_ids)
            # update stream_info with those results from db
            # note: this works correctly because rec_join() and the sql query
            # both return items sorted by "stream_id"
            stream_info[mask_cache_miss] = db_res
            # update cache
            self.cache = np.append(self.cache, db_res).view(np.recarray)
        # apply filtering on issuers and streams if defined
        issuers_filtering = self.issuers is not None
        streams_filtering = self.streams_re_match is not None
        if issuers_filtering or streams_filtering:
            mask_streams = np.ones(stream_info.size, dtype=bool)
            if streams_filtering:
                mask_streams &= self.streams_re_match(stream_info.stream)
                if not mask_streams.any():
                    return  # all logs filtered out
            # when data comes from the db, issuers are already filtered,
            # while data coming from the hub has to be filtered.
            if issuers_filtering:
                mask_streams &= np.isin(stream_info.issuer, self.issuers)
                # filter out wrong issuers
                if not mask_streams.any():
                    return  # all logs filtered out
            # filter data according to mask_streams
            if not mask_streams.all():
                mask_logs = mask_streams[rev]
                logs = logs[mask_logs]
                rev = rev[mask_logs]
        # compute resulting table
        client_logs = np.empty(logs.size, CLIENT_LOG_DT).view(np.recarray)
        client_logs.line = logs.line
        client_logs.timestamp = self.format_timestamps(logs.timestamp)
        client_logs[["issuer", "stream"]] = stream_info[rev][["issuer", "stream"]]
        # send to the client
        return self.send_logs_to_client(client_logs)

    def write_db_logs_to_client(self, db_logs):
        # update the format of timestamps
        db_logs.timestamp = self.format_timestamps(db_logs.timestamp)
        # send to the client
        return self.send_logs_to_client(db_logs)

    def format_timestamps(self, timestamps):
        if self.timestamps_format == "datetime":
            return self.np_datetime_from_ts(timestamps)
        elif self.timestamps_format == "float-s":
            return timestamps
        elif self.timestamps_format == "float-ms":
            return timestamps * 1000
        else:
            raise NotImplementedError('Unexpected "timestamps_format" value.')

    def send_logs_to_client(self, client_logs):
        try:
            if self.sock_file.closed:
                raise IOError()
            if self.output_format == "dict-pickles":
                tuple_of_dicts = np_recarray_to_tuple_of_dicts(client_logs)
                for d in tuple_of_dicts:
                    write_pickle(d, self.sock_file)
            elif self.output_format == "numpy-pickles":
                write_pickle(client_logs, self.sock_file)
            else:
                raise NotImplementedError('Unexpected "output_format" value.')
        except IOError:
            # the socket was supposedly closed.
            print("client log connection closing")
            # notify the hub that we should be removed.
            return False

    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock_file.fileno()

    # this is what we will do depending on the client request params
    def handle_params(self, history, realtime,
                      issuers=None, streams_regexp=None, logline_regexp=None,
                      timestamps_format="datetime", output_format="dict-pickles"):
        if streams_regexp:
            regex = PosixExtendedRegex(streams_regexp)
            self.streams_re_match = np.vectorize(regex.match)
        else:
            self.streams_re_match = None
        if logline_regexp:
            regex = PosixExtendedRegex(logline_regexp)
            self.logline_re_match = np.vectorize(regex.match)
        else:
            self.logline_re_match = None
        if issuers is None:
            self.issuers = None
        else:
            self.issuers = np.array(issuers)
        self.realtime = realtime
        self.timestamps_format = timestamps_format
        self.output_format = output_format
        self.db_params = dict(history=history,
                              issuers=issuers,
                              streams_regexp=streams_regexp,
                              logline_regexp=logline_regexp)
        if realtime:
            self.hub.addHandler(self)
        if history:
            self.phase = PHASE_RETRIEVING_FROM_DB
            self.stream_db_logs()
        else:
            self.phase = PHASE_SENDING_TO_CLIENT

    def _wf_create_server_logs_cursor(self, wf, **env):
        async_db, params = self.manager.db.do_async, self.db_params
        async_db.create_server_logs_cursor(**params).then(wf.next)

    def _wf_save_cursor_name(self, wf, cursor_name, **env):
        wf.update_env(cursor_name = cursor_name)
        wf.next()

    def _wf_step_server_cursor(self, wf, cursor_name, **env):
        async_db = self.manager.db.do_async
        async_db.step_server_cursor(cursor_name, DB_LOGS_BLOCK_SIZE).then(wf.next)

    def _wf_process_logs_block(self, wf, rows, **env):
        # we end the stream when we detect its end
        # (i.e., rows.size < DB_LOGS_BLOCK_SIZE) and
        # when the client disconnects.
        if rows.size > 0:
            res = self.write_db_logs_to_client(rows)
            should_continue = (
                    (res is not False) and
                    (rows.size == DB_LOGS_BLOCK_SIZE))
        else:
            should_continue = False
        if should_continue:
            # we will continue with next block
            wf.insert_steps([
                    self._wf_step_server_cursor,
                    self._wf_process_logs_block
            ])
        wf.next()

    def _wf_delete_server_cursor(self, wf, cursor_name, **env):
        async_db = self.manager.db.do_async
        async_db.delete_server_cursor(cursor_name).then(wf.next)

    def _wf_end_db_logs(self, wf, _, **env):
        # we are done with the history part
        if self.realtime:
            # we can flush the buffer of realtime logs
            if self.realtime_buffer.size > 0:
                self.write_realtime_logs_to_client(self.realtime_buffer.pop())
            # notify that next logs can be sent
            # directly to the client
            self.phase = PHASE_SENDING_TO_CLIENT
        else:
            # no realtime mode, we can quit
            self.close()
        wf.next()

    def stream_db_logs(self):
        # ensure all past logs are commited
        self.manager.logs_to_db.flush()
        # for retrieving db logs asynchronously, we use a workflow object
        steps = [self._wf_create_server_logs_cursor,
                 self._wf_save_cursor_name,
                 self._wf_step_server_cursor,
                 self._wf_process_logs_block,
                 self._wf_delete_server_cursor,
                 self._wf_end_db_logs]
        wf = Workflow(steps)
        wf.run()

    # this is what we do when the event loop detects an event for us
    def handle_event(self, ts):
        if self.db_params is None:
            params = read_pickle(self.sock_file)
            self.handle_params(**params)
        else:
            return False  # no more communication is expected this way

    def close(self):
        self.sock_file.close()


class LoggerFile:
    def __init__(self, logs_manager, stream_name, secondary_file):
        self.logs_manager = logs_manager
        self.stream_name = stream_name
        self.secondary_file = secondary_file
        self.buffer = ""
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
            parts = self.buffer.split("\n")
            if len(parts) == 1:
                break
            self.buffer = parts[-1]
            lines = np.array(parts[:-1])
            # exclude lines tagged __DEBUG__
            mask = (np.char.find(lines, "__DEBUG__") == -1)
            if mask.any():
                self.logs_manager.server_log(self.stream_name, lines=lines[mask])
        self._flushing = False

    def flush(self):
        self.secondary_file.flush()

    def fileno(self):
        return self.secondary_file.fileno()

    @property
    def encoding(self):
        return self.secondary_file.encoding


class LogsManager(object):
    def __init__(self, db, tcp_server, ev_loop):
        self.ev_loop = ev_loop
        self.db = db
        self.server_ip = get_server_ip()
        self.server_log_cache = {}
        self.hub = LogsHub()
        self.logs_to_db = LogsToDBHandler(ev_loop, db)
        self.hub.addHandler(self.logs_to_db)
        self.stream_id_cache = defaultdict(dict)
        tcp_server.register_listener_class(
            req_id=Requests.REQ_DUMP_LOGS, cls=LogsToSocketHandler, manager=self
        )
        tcp_server.register_listener_class(
            req_id=Requests.REQ_NEW_INCOMING_LOGS, cls=LogsStreamListener, manager=self
        )

    def prepare(self):
        self.netconsole = NetconsoleListener(self, WALT_SERVER_NETCONSOLE_PORT)
        self.netconsole.join_event_loop(self.ev_loop)

    def monitor_file(self, fileobj, issuer_ip, stream_name):
        stream_id = self.get_stream_id(issuer_ip, stream_name, "chunk")
        listener = FileListener(self.hub, fileobj, stream_id)
        self.ev_loop.register_listener(listener)
        return listener

    def catch_std_streams(self):
        sys.stdout = LoggerFile(self, "daemon.stdout", sys.__stdout__)
        sys.stderr = LoggerFile(self, "daemon.stderr", sys.__stderr__)

    def get_stream_id(self, issuer_ip, stream_name, mode="line"):
        stream_id = self.stream_id_cache[issuer_ip].get(stream_name, None)
        if stream_id is not None:
            return stream_id
        issuer_info = self.db.select_unique("devices", ip=issuer_ip)
        if issuer_info is None:
            # issuer device is unknown in database,
            # this stream must be ignored
            return None
        issuer_mac = issuer_info.mac
        stream_info = self.db.select_unique(
            "logstreams", issuer_mac=issuer_mac, name=stream_name
        )
        if stream_info:
            # found existing stream
            stream_id = stream_info.id
        else:
            # register new stream
            stream_id = self.db.insert(
                "logstreams",
                returning="id",
                issuer_mac=issuer_mac,
                name=stream_name,
                mode=mode,
            )
        self.stream_id_cache[issuer_ip][stream_name] = stream_id
        return stream_id

    def get_streams_info(self, stream_ids):
        return self.db.execute(
            """SELECT s.id as stream_id, d.name as issuer, s.name as stream
               FROM logstreams s, devices d
               WHERE s.id = ANY(%s)
                 AND s.issuer_mac = d.mac
               ORDER BY s.id
            """, (list(stream_ids),))

    def platform_log(self, stream_name, error=False, **kwargs):
        # print at stdout / stderr too
        std = sys.__stderr__ if error else sys.__stdout__
        # record as log
        self.server_log("platform." + stream_name, secondary_file=std, **kwargs)

    def server_log(self, stream_name, **kwargs):
        if stream_name not in self.server_log_cache:
            self.server_log_cache[stream_name] = self.get_stream_id(
                self.server_ip, stream_name
            )
        stream_id = self.server_log_cache[stream_name]
        self.hub.log(stream_id, **kwargs)

    def forget_device(self, device):
        self.logs_to_db.flush()
        if device.ip in self.stream_id_cache:
            del self.stream_id_cache[device.ip]
        self.netconsole.forget_ip(device.ip)

    # Look for a checkpoint. Return a tuple.
    # If the result conforms to 'expected', return (True, <checkpoint_found_or_none>)
    # If not or an issue occured, return (False,)
    def get_checkpoint(self, requester, cp_name, expected=True):
        username = requester.get_username()
        if not username:
            return (False,)  # client already disconnected, give up
        cp_info = self.db.select_unique(
            "checkpoints", name=cp_name, username=requester.get_username()
        )
        if expected:
            if cp_info is None:
                requester.stderr.write(
                    "Failed: no checkpoint with this name '%s'.\n" % cp_name
                )
                return (False,)
            else:
                # datetime to float conversion
                cp_info.timestamp = cp_info.timestamp.timestamp()
                return (True, cp_info)
        if not expected:
            if cp_info is None:
                return (True,)  # ok
            else:
                requester.stderr.write(
                    "Failed: a checkpoint with this name already exists.\n"
                )
                return (False,)

    def add_checkpoint(self, requester, cp_name, date):
        # expect no existing checkpoint with the same name
        if not self.get_checkpoint(requester, cp_name, expected=False)[0]:
            return
        if date:
            # convert to datetime
            date = datetime.fromtimestamp(date)
        else:
            date = datetime.now()
        self.db.insert(
            "checkpoints",
            name=cp_name,
            username=requester.get_username(),
            timestamp=date,
        )
        requester.stdout.write(
            "New checkpoint %s recorded at server time: %s.\n" % (cp_name, date)
        )

    def remove_checkpoint(self, requester, cp_name):
        # expect a checkpoint with this name
        if not self.get_checkpoint(requester, cp_name, expected=True)[0]:
            return
        self.db.delete("checkpoints", name=cp_name, username=requester.get_username())
        requester.stdout.write("Done.\n")

    def list_checkpoints(self, requester):
        username = requester.get_username()
        if not username:
            return None  # client already disconnected, give up
        res = self.db.select("checkpoints", username=username)
        if len(res) == 0:
            requester.stdout.write("You own no checkpoints.\n")
        else:
            # re-execute because we don't want the 'username' column.
            requester.stdout.write(
                self.db.pretty_printed_select(
                    """
                    SELECT timestamp, name FROM checkpoints
                    WHERE username = %s;
            """,
                    (username,),
                )
                + "\n"
            )

    def get_checkpoint_time(self, requester, cp_name):
        res = self.get_checkpoint(requester, cp_name, expected=True)
        if not res[0]:
            return
        cp_info = res[1]
        return cp_info.timestamp
