from walt.common.version import __version__
from walt.common.tcp import Requests
from walt.common.apilink import APIChannel, AttrCallAggregator
from walt.server.process import RPCService
from socket import error as SocketError

class APISessionManager(object):
    REQ_ID = Requests.REQ_API_SESSION
    REQUESTER_API_IGNORED = (EOFError,)
    next_session_id = 0
    def __init__(self, process, sock_file, **kwargs):
        self.process = process
        self.main = process.main
        self.sock_file = sock_file
        self.target_api = None
        self.api_channel = APIChannel(sock_file)
        self.remote_ip, remote_port = sock_file.getpeername()
        self.session_id = None
        self.sent_tasks = False
        self.requester = AttrCallAggregator(self.forward_requester_request)
        local_service = RPCService(requester = self.requester)
        self.rpc_session = self.main.create_session(local_service = local_service)
    def record_task(self, attr, args, kwargs):
        self.sent_tasks = True
        self.rpc_session.do_async.run_task(self.session_id, self.target_api, self.remote_ip,
                                           attr, args, kwargs).then(
            self.return_result
        )
    def fileno(self):
        return self.api_channel.fileno()
    def handle_event(self, ts):
        if not self.target_api:
            return self.init_session()
        else:
            return self.handle_api_call()
    def read_api_channel(self):
        # exceptions may occur if the client disconnects.
        # we should ignore those.
        try:
            return self.api_channel.read()
        except (EOFError, SyntaxError, OSError, SocketError):
            return None
    def handle_api_call(self):
        try:
            event = self.read_api_channel()
            if event == None:
                return False
            # e.g. if you send ('CLOSE',) instead of ('API_CALL','<func>',<args>,<kwargs>)
            # the connection will be closed from server side.
            cmd = event[0]
            if cmd == 'SET_MODE':
                self.api_channel.set_mode(event[1])
                return True
            elif cmd == 'API_CALL':
                if len(event) != 4:
                    return False
                attr, args, kwargs = event[1:]
                print('hub api_call:', self.target_api, attr, args, kwargs)
                self.record_task(attr, args, kwargs)
                return True
            return False
        except:
            return False
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
            self.target_api = self.sock_file.readline().decode('UTF-8').strip()
            self.session_id = APISessionManager.next_session_id
            APISessionManager.next_session_id += 1
            self.sock_file.write(b"%s\n" % str(__version__).encode('UTF-8'))
            return True
        except:
            return False
    def close(self):
        if self.sent_tasks:
            self.rpc_session.do_sync.destroy_session(self.session_id)
        self.sock_file.close()
    def forward_requester_request(self, path, args, kwargs):
        args = args[1:] # discard 1st arg, rpc context
        try:
            self.api_channel.write('API_CALL', path, args, kwargs)
            res = self.read_api_channel()
            if res == None:
                return None
            return res[1]
        except APISessionManager.REQUESTER_API_IGNORED:
            pass
        return None

