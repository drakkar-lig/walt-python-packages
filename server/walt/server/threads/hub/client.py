from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.versions import API_VERSIONING
from walt.common.apilink import APIService
from walt.server.threads.hub.task import Task, ClientTask, HubTask
from walt.common.daemon import RPyCServer
import inspect

# exceptions may occur if the client disconnects.
# we should ignore those.
# the following object allows to safely access the remote
# API, ignoring such exceptions (and returning None when
# it occurs).
class FailsafeRemoteAPI(object):
    IGNORED = (ReferenceError, EOFError, AttributeError)
    def __init__(self, remote_api_endpoint, path = ()):
        self._api = remote_api_endpoint
        self._path = path
        self.exposed___getattr__ = self.__getattr__
        self.exposed___call__ = self.__call__
    def __getattr__(self, attr):
        return FailsafeRemoteAPI(self._api, self._path + (attr,))
    def walk(self):
        obj = self._api
        for attr in self._path:
            obj = getattr(obj, attr)
        return obj
    def __call__(self, *args, **kwargs):
        print 'hub:', '.'.join(self._path), 'called'
        try:
            func = self.walk()
            return func(*args, **kwargs)
        except FailsafeRemoteAPI.IGNORED:
            pass
        return None

class LinkInfo(object):
    INDEX = 0
    def __init__(self, remote_api, remote_ip):
        self.remote_api = remote_api
        self.exposed_remote_api = remote_api
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
        print 'hub api_call:', api, attr, args, kwargs
        if self.target_api == None:
            self.target_api = api
            remote_api = FailsafeRemoteAPI(self._conn.root)
            remote_ip = self._conn._config['endpoints'][1][0]
            self.link_info = LinkInfo(remote_api, remote_ip)
            self.record_task('on_connect', [], {}, cls=HubTask)
        self.record_task(attr, args, kwargs)
    def exposed_get_api_version(self, api):
        print 'hub get_api_version', api
        return API_VERSIONING[api][0]
    def record_task(self, attr, args, kwargs, cls=ClientTask):
        print 'hub record_task:', attr, args, kwargs
        t = cls(self.target_api, attr, args, kwargs, self.link_info)
        self.tasks.insert(0, t)
        # notify the server that we have a new task
        self.main.pipe.send(0)
    def on_connect(self):
        print 'hub: on_connect'
        # for now we do not know what is the target API, so we
        # cannot pass it the 'on_connect' event.
        # we do it above when the peer performs its 1st api call.
    def on_disconnect(self):
        print 'hub: on_disconnect'
        if self.target_api != None:
            self.record_task('on_disconnect', [], {}, cls=HubTask)

class RPyCClientServer(RPyCServer):
    def __init__(self, tasks, connection_to_main):
        service = RPyCClientService(tasks, connection_to_main)
        RPyCServer.__init__(self, service, port = WALT_SERVER_DAEMON_PORT)
