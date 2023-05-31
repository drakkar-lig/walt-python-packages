from socket import IPPROTO_TCP, TCP_NODELAY
from socket import error as SocketError

from walt.common.apilink import APIChannel, AttrCallAggregator
from walt.common.tcp import Requests
from walt.common.version import __version__
from walt.server.process import RPCService


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
        self.stack_of_client_tasks = []
        self.requester = AttrCallAggregator(self.forward_requester_request)
        local_service = RPCService(requester=self.requester)
        self.rpc_session = self.main.create_session(local_service=local_service)
        self.sock_file.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)  # disable Nagle

    def record_task(self, attr, args, kwargs):
        self.sent_tasks = True
        self.rpc_session.do_async.run_task(
            self.session_id, self.target_api, self.remote_ip, attr, args, kwargs
        ).then(self.return_result)

    def fileno(self):
        return self.api_channel.fileno()

    def handle_event(self, ts):
        if not self.target_api:
            return self.init_session()
        else:
            return self.handle_client_message()

    def read_api_channel(self):
        # exceptions may occur if the client disconnects.
        # we should ignore those.
        try:
            return self.api_channel.read()
        except (EOFError, SyntaxError, OSError, SocketError):
            return None

    def handle_client_message(self):
        try:
            event = self.read_api_channel()
            if event is None:
                return False
            # e.g. if you send ('CLOSE',) instead of
            # ('API_CALL','<func>',<args>,<kwargs>) the connection will be closed
            # from server side.
            cmd = event[0]
            if cmd == "SET_MODE":
                self.api_channel.set_mode(event[1])
                return True
            elif cmd == "API_CALL":
                if len(event) != 4:
                    return False
                attr, args, kwargs = event[1:]
                print("hub api_call:", self.target_api, attr, args, kwargs)
                self.record_task(attr, args, kwargs)
                return True
            elif cmd == "RESULT":
                if len(event) != 2:
                    return False
                if len(self.stack_of_client_tasks) == 0:
                    return False
                task = self.stack_of_client_tasks.pop()
                task.return_result(event[1])
                return True
            return False
        except Exception:
            return False

    def return_result(self, res):
        # client might already be disconnected (ctrl-C),
        # thus we ignore errors.
        try:
            self.api_channel.write("RESULT", res)
        except Exception:
            self.close()

    def init_session(self):
        try:
            self.target_api = self.sock_file.readline().decode("UTF-8").strip()
            self.session_id = APISessionManager.next_session_id
            APISessionManager.next_session_id += 1
            self.sock_file.write(b"%s\n" % str(__version__).encode("UTF-8"))
            return True
        except Exception:
            return False

    def close(self):
        for task in reversed(self.stack_of_client_tasks):
            self.handle_requester_failed_task(task)
        if self.sent_tasks:
            self.rpc_session.do_sync.destroy_session(self.session_id)
        self.sock_file.close()

    def forward_requester_request(self, path, args, kwargs):
        context, args = args[0], args[1:]  # 1st arg is rpc context
        # print('main->hub requester call:', path, args, kwargs)
        context.task.set_async()
        if self.sock_file.closed:
            self.handle_requester_failed_task(context.task)
        else:
            self.stack_of_client_tasks.append(context.task)
            try:
                self.api_channel.write("API_CALL", path, args, kwargs)
            except APISessionManager.REQUESTER_API_IGNORED:
                self.close()

    def handle_requester_failed_task(self, task):
        # If the client disconnects, we may silently ignore many calls
        # (e.g., stdout.write()), thus me chose to return None here.
        # Note that get_username(), is_alive() will also return None
        # in this case.
        task.return_result(None)
