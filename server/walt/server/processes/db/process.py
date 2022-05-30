from walt.common.process import EvProcess, RPCProcessConnector
from walt.server.processes.db.db import ServerDB

class ServerDBProcess(EvProcess):
    def __init__(self, tman, level):
        EvProcess.__init__(self, tman, 'server-db', level)
        self.db = ServerDB()
        self.main = RPCProcessConnector(self.db, local_context=False)
        self.blocking = RPCProcessConnector(self.db, local_context=False)

    def prepare(self):
        self.register_listener(self.main)
        self.register_listener(self.blocking)
        self.db.plan_auto_commit(self.ev_loop)
