from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.service import RPyCService
from walt.server.threads.hub.task import Task
from walt.common.daemon import RPyCServer

@RPyCService
class RPyCClientService(object):
    def __init__(self, tasks, connection_to_main):
        self.main = connection_to_main
        self.tasks = tasks
    def __getattr__(self, attr):
        requester = self._conn.root
        remote_ip = self._conn._config['endpoints'][1][0]
        def func(*args, **kwargs):
            t = Task('cs', attr, args, kwargs, requester, remote_ip)
            self.tasks.insert(0, t)
            # notify the server that we have a new task
            self.main.pipe.send(0)
        return func

class RPyCClientServer(RPyCServer):
    def __init__(self, tasks, connection_to_main):
        service = RPyCClientService(tasks, connection_to_main)
        RPyCServer.__init__(self, service, port = WALT_SERVER_DAEMON_PORT)
