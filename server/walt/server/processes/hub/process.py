from walt.server.process import EvProcess, RPCProcessConnector


class ServerHubProcess(EvProcess):
    def __init__(self, tman, level):
        EvProcess.__init__(self, tman, "server-hub", level)
        self.main = RPCProcessConnector(label="hub-to-main")
        tman.attach_file(self, self.main)
        # Requests of walt clients (CSAPI) are held until server-main
        # calls release_csapi() at the end of its startup (which includes
        # the startup of virtual nodes). The other APIs are forwarded
        # immediately, because the startup steps use them (e.g.,
        # walt-exports-update calls SSAPI.get_exports_info()).
        self.holding_csapi = True
        self.held_csapi_requests = []

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
        self.ev_loop.register_listener(self.main.pipe, self.main)

    def release_csapi(self, rpc_context):
        self.holding_csapi = False
        held_requests, self.held_csapi_requests = self.held_csapi_requests, []
        for session_manager, attr, args, kwargs in held_requests:
            session_manager.record_task(attr, args, kwargs)

    def cleanup(self):
        self.tcp_server.shutdown()
