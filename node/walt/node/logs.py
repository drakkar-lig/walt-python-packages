import os
from time import time
from walt.node.const import SERVER_LOGS_FIFO
from walt.node.tools import lookup_server_ip
from walt.common.fifo import open_readable_fifo
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import write_pickle, client_socket, \
                            Requests

LOGCONN_CACHE_MIN_DELAY = 15
LOGCONN_CACHE_CLEANUP = 0

class LogsFlowToServer(object):
    server_ip = lookup_server_ip()
    def __init__(self, stream_name):
        s = client_socket(LogsFlowToServer.server_ip, WALT_SERVER_TCP_PORT)
        self.stream = s.makefile()
        Requests.send_id(self.stream, Requests.REQ_NEW_INCOMING_LOGS)
        write_pickle(stream_name, self.stream)
        self.last_used = time()
    def log(self, **kwargs):
        write_pickle(kwargs, self.stream)
        self.last_used = time()
    def close(self):
        self.stream.close()

class LogsFifoMonitor(object):
    def __init__(self, stream_name, path):
        self.f = open_readable_fifo(path)
        self.conn = LogsFlowToServer(stream_name)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.f.fileno()

    # when the event loop detects an event for us,
    # read the log line and process it
    def handle_event(self, ts):
        line = self.f.readline()
        if line == '':  # empty read
            return False # remove from loop
        self.conn.log(line=line.strip(), timestamp=ts)

    def close(self):
        self.conn.close()
        self.f.close()

class LogsConnCache(object):
    def __init__(self):
        self.conns = {}
    def get(self, stream_name):
        if stream_name not in self.conns:
            self.conns[stream_name] = LogsFlowToServer(stream_name)
        return self.conns[stream_name]
    def cleanup(self):
        limit = time() - LOGCONN_CACHE_MIN_DELAY
        for name, stream in self.conns.items():
            if stream.last_used < limit:
                stream.close()
                del self.conns[name]

class LogsFifoServer(object):
    def __init__(self):
        self.fifo = open_readable_fifo(SERVER_LOGS_FIFO)
        self.conn_cache = LogsConnCache()

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)
        ev_loop.plan_event(
            ts = time(),
            target = self,
            repeat_delay = LOGCONN_CACHE_MIN_DELAY,
            ev_type = LOGCONN_CACHE_CLEANUP
        )

    def handle_planned_event(self, ev_type):
        assert(ev_type == LOGCONN_CACHE_CLEANUP)
        self.conn_cache.cleanup()

    # let the event loop know what we are reading on
    def fileno(self):
        return self.fifo.fileno()

    # when the event loop detects an event for us,
    # read the request and process it
    def handle_event(self, ts):
        req = self.fifo.readline().split()
        if req[0] == 'MONITOR':
            listener = LogsFifoMonitor(*req[1:])
            self.ev_loop.register_listener(listener)
        elif req[0] == 'LOG':
            stream_name, line = req[1], ' '.join(req[2:])
            self.conn_cache.get(stream_name).log(
                        line=line.strip(), timestamp=ts)
        elif req[0] == 'TSLOG':
            ts, stream_name, line = \
                float(req[1]), req[2], ' '.join(req[3:])
            self.conn_cache.get(stream_name).log(
                        line=line.strip(), timestamp=ts)

    def close(self):
        self.fifo.close()

