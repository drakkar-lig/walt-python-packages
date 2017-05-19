from walt.common.thread import EvThread
from walt.common.tcp import TCPServer
from walt.common.thread import RPCThreadConnector
from walt.server.threads.hub.client import APISessionManager
from walt.common.constants import WALT_SERVER_DAEMON_PORT

TCP_LISTENER_CLASSES = ( APISessionManager, )

class ServerHubThread(EvThread):
    def __init__(self, tman):
        EvThread.__init__(self, tman, 'server-hub')
        self.main = RPCThreadConnector(self)
        self.tcp_server = TCPServer(WALT_SERVER_DAEMON_PORT)
        for cls in TCP_LISTENER_CLASSES:
            self.tcp_server.register_listener_class(
                    req_id = cls.REQ_ID,
                    cls = cls,
                    thread = self)

    def prepare(self):
        self.tcp_server.join_event_loop(self.ev_loop)
        self.register_listener(self.main)
