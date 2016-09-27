from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.versions import API_VERSIONING
from walt.common.apilink import APIService, RPyCProxy
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

@APIService
class RPyCClientService(object):
    def __init__(self, tasks, connection_to_main):
        self.main = connection_to_main
        self.tasks = tasks
        self.link_info = None
        self.target_api = None
    def exposed_api_call(self, api, attr, *args, **kwargs):
        if self.target_api == None:
            self.target_api = api
            self.record_task('on_connect', [], {}, cls=HubTask)
        self.record_task(attr, args, kwargs)
    def exposed_get_api_version(self, api):
        return API_VERSIONING[api][0]
    def record_task(self, attr, args, kwargs, cls=ClientTask):
        t = cls(self.target_api, attr, args, kwargs, self.link_info)
        self.tasks.insert(0, t)
        # notify the server that we have a new task
        self.main.pipe.send(0)
    def on_connect(self):
        requester = self._conn.root
        remote_ip = self._conn._config['endpoints'][1][0]
        self.link_info = LinkInfo(requester, remote_ip)
        # for now we do not know what is the target API, so we
        # cannot pass it the 'on_connect' event.
        # we do it above when the peer performs its 1st api call.
    def on_disconnect(self):
        if self.target_api != None:
            self.record_task('on_disconnect', [], {}, cls=HubTask)

class RPyCClientServer(RPyCServer):
    def __init__(self, tasks, connection_to_main):
        service = RPyCClientService(tasks, connection_to_main)
        RPyCServer.__init__(self, service, port = WALT_SERVER_DAEMON_PORT)
