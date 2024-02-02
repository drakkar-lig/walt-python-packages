from walt.server.process import EvProcess, RPCProcessConnector, SyncRPCProcessConnector


class ServerBlockingProcess(EvProcess):
    def __init__(self, tman, level: int):
        EvProcess.__init__(self, tman, "server-blocking", level)
        self.main = RPCProcessConnector(label="blocking-to-main")
        tman.attach_file(self, self.main)
        self.db = SyncRPCProcessConnector(label="blocking-to-db")
        tman.attach_file(self, self.db)

    def prepare(self):
        from walt.server.processes.blocking.service import BlockingTasksService
        service = BlockingTasksService()
        service.db = self.db
        self.main.configure(service)
        self.db.configure()
        self.ev_loop.register_listener(self.main)
        self.ev_loop.register_listener(self.db)
