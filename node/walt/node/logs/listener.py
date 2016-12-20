from threading import Thread
from walt.common.fifo import open_readable_fifo
from walt.node.logs.monitor import handle_monitor_request
from walt.node.logs.cache import LogsConnCache
from walt.node.logs.flow import LogsFlowToServer

WALT_LOGS_FIFO = '/var/lib/walt/logs.fifo'

class LogsFifoListener(object):
    def __init__(self):
        self.fifo = open_readable_fifo(WALT_LOGS_FIFO)
        self.conn_cache = LogsConnCache()

    def join_event_loop(self, ev_loop):
        ev_loop.register_listener(self)
        self.conn_cache.join_event_loop(ev_loop)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.fifo.fileno()

    # when the event loop detects an event for us,
    # read the request and process it
    def handle_event(self, ts):
        req = self.fifo.readline()
        if req == '':
            # malformed
            return
        req = req.split()
        if req[0] == 'MONITOR':
            # we have to communicate with a walt-monitor process.
            # this will take time, let's create a thread to
            # handle this.
            t = Thread(target = handle_monitor_request,
                       args = req[1:])
            t.start()
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

