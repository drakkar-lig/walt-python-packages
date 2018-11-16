from walt.common.version import __version__
from walt.common.tcp import Requests
from walt.common.apilink import APIChannel, AttrCallAggregator

class APISessionManager(object):
    REQ_ID = Requests.REQ_API_SESSION
    REQUESTER_API_IGNORED = (EOFError,)
    def __init__(self, thread, sock_file, **kwargs):
        self.thread = thread
        self.main = thread.main
        self.sock_file = sock_file
        self.target_api = None
        self.api_channel = APIChannel(sock_file)
        self.remote_ip, remote_port = sock_file.getpeername()
        self.session_id = None
        self.requester = AttrCallAggregator(self.forward_requester_request)
        self.rpc_session = self.main.local_service(self.requester)
    def record_task(self, attr, args, kwargs):
        self.rpc_session.async.run_task(self.session_id, attr, args, kwargs).then(
            self.return_result
        )
    def fileno(self):
        return self.api_channel.fileno()
    def handle_event(self, ts):
        if not self.target_api:
            return self.init_session()
        else:
            return self.handle_api_call()
    def handle_api_call(self):
        event = self.api_channel.read()
        if event == None:
            return False
        # e.g. if you send ('CLOSE',) instead of ('API_CALL','<func>',<args>,<kwargs>)
        # the connection will be closed from server side.
        if len(event) != 4:
            return False
        attr, args, kwargs = event[1:]
        print 'hub api_call:', self.target_api, attr, args, kwargs
        self.record_task(attr, args, kwargs)
        return True
    def return_result(self, res):
        # client might already be disconnected (ctrl-C),
        # thus we ignore errors.
        try:
            if isinstance(res, BaseException):
                self.api_channel.write('EXCEPTION', str(res))
            else:
                self.api_channel.write('RESULT', res)
        except:
            pass
    def init_session(self):
        try:
            self.target_api = self.sock_file.readline().strip()
            self.session_id = self.rpc_session.sync.create_session(
                                self.target_api, self.remote_ip)
            self.sock_file.write("%d\n" % int(__version__))
            return True
        except:
            return False
    def close(self):
        if self.session_id != None:
            self.rpc_session.sync.destroy_session(self.session_id)
        self.sock_file.close()
    def forward_requester_request(self, path, args, kwargs):
        args = args[1:] # discard 1st arg, rpc context
        try:
            self.api_channel.write('API_CALL', path, args, kwargs)
            res = self.api_channel.read()
            if res == None:
                return None
            return res[1]
        except REQUESTER_API_IGNORED:
            pass
        return None

