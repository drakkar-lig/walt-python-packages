from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.service import RPyCService, RPyCProxy
from walt.server.threads.hub.task import Task, ClientTask, HubTask
from walt.common.daemon import RPyCServer

# we let the main thread access the requester, which is an object
# of the client, but since we are in the middle of 2 RPyC layers
# we have to wrap it as a RPyCProxy object.
class LinkInfo(object):
    INDEX = 0
    def __init__(self, requester, remote_ip):
        self.requester = requester
        self.exposed_requester = RPyCProxy(requester, ignore_spec = Task.IGNORED)
        self.exposed_remote_ip = remote_ip
        self.exposed_link_id = LinkInfo.INDEX
        LinkInfo.INDEX += 1

@RPyCService
class RPyCClientService(object):
    def __init__(self, tasks, connection_to_main):
        self.main = connection_to_main
        self.tasks = tasks
        self.link_info = None
    def __getattr__(self, attr):
        def func(*args, **kwargs):
            self.record_task('CSAPI', attr, args, kwargs)
        return func
    def record_task(self, target_api, attr, args, kwargs, cls=ClientTask):
        t = cls(target_api, attr, args, kwargs, self.link_info)
        self.tasks.insert(0, t)
        # notify the server that we have a new task
        self.main.pipe.send(0)
    def on_connect(self):
        requester = self._conn.root
        remote_ip = self._conn._config['endpoints'][1][0]
        self.link_info = LinkInfo(requester, remote_ip)
        self.record_task('CSAPI', 'on_connect', [], {}, cls=HubTask)
    def on_disconnect(self):
        self.record_task('CSAPI', 'on_disconnect', [], {}, cls=HubTask)

class RPyCClientServer(RPyCServer):
    def __init__(self, tasks, connection_to_main):
        service = RPyCClientService(tasks, connection_to_main)
        RPyCServer.__init__(self, service, port = WALT_SERVER_DAEMON_PORT)
