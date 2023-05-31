from walt.server.process import EvProcess, RPCProcessConnector
from walt.server.processes.db.db import ServerDB


class ServerDBProcess(EvProcess):
    def __init__(self, tman, level):
        EvProcess.__init__(self, tman, "server-db", level)
        self.db = ServerDB()
        self.main = RPCProcessConnector(
            self.db, local_context=False, label="db-to-main"
        )
        tman.attach_file(self, self.main)
        self.blocking = RPCProcessConnector(
            self.db, local_context=False, label="db-to-blocking"
        )
        tman.attach_file(self, self.blocking)

    def prepare(self):
        self.register_listener(self.main)
        self.register_listener(self.blocking)
        self.db.prepare()
        self.db.plan_auto_commit(self.ev_loop)
