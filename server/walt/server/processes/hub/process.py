from walt.common.process import EvProcess
from walt.common.tcp import TCPServer
from walt.common.process import RPCProcessConnector
from walt.server.processes.hub.client import APISessionManager
from walt.common.constants import WALT_SERVER_DAEMON_PORT

TCP_LISTENER_CLASSES = ( APISessionManager, )

class ServerHubProcess(EvProcess):
    def __init__(self, tman, level):
        EvProcess.__init__(self, tman, 'server-hub', level)
        self.main = RPCProcessConnector(self, label = 'hub-to-main')
        self.tcp_server = TCPServer(WALT_SERVER_DAEMON_PORT)
        for cls in TCP_LISTENER_CLASSES:
            self.tcp_server.register_listener_class(
                    req_id = cls.REQ_ID,
                    cls = cls,
                    process = self)

    def prepare(self):
        self.tcp_server.join_event_loop(self.ev_loop)
        self.register_listener(self.main)
