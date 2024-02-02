from walt.server.process import EvProcess, RPCProcessConnector


class ServerDBProcess(EvProcess):
    def __init__(self, tman, level):
        EvProcess.__init__(self, tman, "server-db", level)
        self.main = RPCProcessConnector(
            local_context=False, label="db-to-main"
        )
        tman.attach_file(self, self.main)
        self.blocking = RPCProcessConnector(
            local_context=False, label="db-to-blocking"
        )
        tman.attach_file(self, self.blocking)

    def prepare(self):
        from walt.server.processes.db.db import ServerDB
        self.db = ServerDB()
        # self.db is the local service we provide
        # to main and blocking processes
        self.main.configure(self.db)
        self.blocking.configure(self.db)
        self.ev_loop.register_listener(self.main)
        self.ev_loop.register_listener(self.blocking)
        self.db.prepare()
        self.db.plan_auto_commit(self.ev_loop)
