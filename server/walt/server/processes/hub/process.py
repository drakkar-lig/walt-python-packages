from walt.server.process import EvProcess, RPCProcessConnector


class ServerHubProcess(EvProcess):
    def __init__(self, tman, level):
        EvProcess.__init__(self, tman, "server-hub", level)
        self.main = RPCProcessConnector(label="hub-to-main")
        tman.attach_file(self, self.main)

    def prepare(self):
        from walt.common.constants import WALT_SERVER_DAEMON_PORT
        from walt.common.tcp import TCPServer
        from walt.server.processes.hub.client import APISessionManager
        self.tcp_server = TCPServer(WALT_SERVER_DAEMON_PORT)
        self.tcp_server.register_listener_class(
            req_id=APISessionManager.REQ_ID, cls=APISessionManager, process=self
        )
        self.tcp_server.prepare(self.ev_loop)
        self.main.configure(self)
        self.ev_loop.register_listener(self.main)

    def cleanup(self):
        self.tcp_server.shutdown()
