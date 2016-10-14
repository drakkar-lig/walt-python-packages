from walt.common.versions import API_VERSIONING
from walt.server.threads.hub.task import ClientTask, HubTask
from walt.common.tcp import Requests
from walt.common.apilink import APIChannel, AttrCallAggregator

class LinkInfo(object):
    INDEX = 0
    def __init__(self, remote_api, remote_ip):
        self.remote_api = remote_api
        self.exposed_remote_api = remote_api
        self.exposed_remote_ip = remote_ip
        self.exposed_link_id = LinkInfo.INDEX
        LinkInfo.INDEX += 1

class RemoteAPI(AttrCallAggregator):
    IGNORED = (EOFError,)
    def __init__(self, api_channel):
        self.api_channel = api_channel
        AttrCallAggregator.__init__(self, self.attr_call)
        # since this object will be accessed from the main thread,
        # we must expose these two methods of the base class
        self.exposed___getattr__ = self.__getattr__
        self.exposed___call__ = self.__call__
    def attr_call(self, path, args, kwargs):
        try:
            self.api_channel.write('API_CALL', path, args, kwargs)
            res = self.api_channel.read()
            if res == None:
                return None
            return res[1]
        except RemoteAPI.IGNORED:
            pass
        return None

class APISessionManager(object):
    REQ_ID = Requests.REQ_API_SESSION
    def __init__(self, thread, sock, sock_file, **kwargs):
        self.main = thread.main
        self.tasks = thread.tasks
        self.sock_file = sock_file
        self.target_api = None
        self.api_channel = APIChannel(sock_file)
        remote_ip, remote_port = sock.getpeername()
        remote_api = RemoteAPI(self.api_channel)
        self.link_info = LinkInfo(remote_api, remote_ip)
    def record_task(self, attr, args, kwargs, cls=ClientTask):
        print 'hub record_task:', attr, args, kwargs
        t = cls(self.target_api, attr, args, kwargs, self.link_info)
        self.tasks.insert(0, t)
        # notify the server that we have a new task
        self.main.pipe.send(0)
    def fileno(self):
        return self.api_channel.fileno()
    def handle_event(self, ts):
        if not self.target_api:
            return self.init_target_api()
        else:
            return self.handle_api_call()
    def handle_api_call(self):
        event = self.api_channel.read()
        if event == None:
            return False
        attr, args, kwargs = event[1:]
        print 'hub api_call:', self.target_api, attr, args, kwargs
        self.record_task(attr, args, kwargs)
        return True
    def init_target_api(self):
        try:
            self.target_api = self.sock_file.readline().strip()
            self.sock_file.write("%d\n" % API_VERSIONING[self.target_api][0])
            self.record_task('on_connect', [], {}, cls=HubTask)
            return True
        except:
            return False
    def close(self):
        if self.target_api != None:
            self.record_task('on_disconnect', [], {}, cls=HubTask)
        self.sock_file.close()

