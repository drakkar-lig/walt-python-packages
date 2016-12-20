from time import time
from walt.node.logs.flow import LogsFlowToServer

# User may issue multiple walt-echo commands, resulting
# in many tcp connections to the server.
# In order to avoid this, we keep a cache of connections
# temporarily, one per stream name.

LOGCONN_CACHE_MIN_DELAY = 15
LOGCONN_CACHE_CLEANUP = 0

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
    def join_event_loop(self, ev_loop):
        ev_loop.plan_event(
            ts = time(),
            target = self,
            repeat_delay = LOGCONN_CACHE_MIN_DELAY,
            ev_type = LOGCONN_CACHE_CLEANUP
        )

    def handle_planned_event(self, ev_type):
        assert(ev_type == LOGCONN_CACHE_CLEANUP)
        self.cleanup()

