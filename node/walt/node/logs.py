import os
from walt.node.const import SERVER_LOGS_FIFO
from walt.node.tools import lookup_server_ip
from walt.common.tools import failsafe_mkfifo
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import write_pickle, client_socket, \
                            Requests


# When a Fifo is open for reading, it will block
# until another process opens it for writing,
# and vice-versa.
# This can be avoided by specifying the O_NONBLOCK flag.
# But then, if we use a fifo opened with O_RDONLY | O_NONBLOCK
# and send data using e.g. echo test > $FIFO, the reading
# side will receive EOF when the echo command closes the fifo file.
# It the following object, we open it in O_RDWR mode
# in order to avoid this (linux specific).
class HookedFifo(object):
    def __init__(self, path):
        self.path = path
    def make(self):
        failsafe_mkfifo(self.path)
    def open_for_reading(self):
        self.f_read = os.fdopen(
            os.open(self.path, os.O_RDWR | os.O_NONBLOCK))
    def readline(self):
        return self.f_read.readline()
    def fileno(self):
        return self.f_read.fileno()
    def close(self):
        self.f_read.close()
    def is_valid(self):
        return os.path.exists(self.path)

class LogsFlowToServer(object):
    def __init__(self, walt_server_host):
        s = client_socket(walt_server_host, WALT_SERVER_TCP_PORT)
        self.stream = s.makefile()
    def start_new_incoming_logstream(self, stream_name):
        Requests.send_id(self.stream, Requests.REQ_NEW_INCOMING_LOGS)
        write_pickle(stream_name, self.stream)
    def log(self, **kwargs):
        write_pickle(kwargs, self.stream)
    def close(self):
        self.stream.close()

class LogsFifoMonitor(object):
    server_ip = lookup_server_ip()
    def __init__(self, stream_name, path):
        self.f = HookedFifo(path)
        self.f.open_for_reading()
        self.conn = LogsFlowToServer(
                    LogsFifoMonitor.server_ip)
        self.conn.start_new_incoming_logstream(stream_name)

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

    def is_valid(self):
        return self.f.is_valid()

class LogsFifoServer(object):
    def __init__(self):
        self.fifo = HookedFifo(SERVER_LOGS_FIFO)
        self.fifo.make()
        self.fifo.open_for_reading()

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)

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

    def close(self):
        self.fifo.close()

