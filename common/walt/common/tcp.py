import socket, cPickle as pickle
from walt.common.tools import set_close_on_exec
from walt.common.io import SmartFile

class Requests(object):
    REQ_NEW_INCOMING_LOGS = 0
    REQ_DUMP_LOGS = 1
    REQ_SQL_PROMPT = 2
    REQ_DOCKER_PROMPT = 3
    REQ_NODE_CMD = 4
    REQ_DEVICE_PING = 5
    REQ_TAR_FROM_IMAGE = 6
    REQ_TAR_TO_IMAGE = 7
    REQ_TAR_FROM_NODE = 8
    REQ_TAR_TO_NODE = 9
    REQ_API_SESSION = 10
    REQ_TCP_TO_NODE = 11
    REQ_FAKE_TFTP_GET = 12

    # the request id message may be specified directly as
    # as a decimal string (e.g. '4') or by the corresponding
    # name (e.g. 'REQ_NODE_CMD')
    @staticmethod
    def get_id(s):
        try:
            return int(s)
        except:
            try:
                return getattr(Requests, s)
            except:
                return None
    @staticmethod
    def read_id(stream):
        try:
            return Requests.get_id(stream.readline().strip())
        except:
            return None
    @staticmethod
    def send_id(stream, req_id):
        stream.write('%d\n' % req_id)
        stream.flush()

def read_pickle(stream):
    try:
        return pickle.load(stream)
    except Exception as e:
        return None

def write_pickle(obj, stream):
    pickle.dump(obj, stream, pickle.HIGHEST_PROTOCOL)
    stream.flush()

class SmartSocketFile(SmartFile):
    def __init__(self, sock):
        self.sock = sock
        sock_r = sock.makefile('r', 0)
        sock_w = sock.makefile('w', 0)
        SmartFile.__init__(self, sock_r, sock_w)
    def shutdown(self, mode):
        return self.sock.shutdown(mode)
    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
            SmartFile.close(self)
    def getpeername(self):
        return self.sock.getpeername()

def client_sock_file(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # set close-on-exec flag (subprocesses should not inherit it)
    set_close_on_exec(s, True)
    s.connect((host, port))
    return SmartSocketFile(s)

class ServerSocketWrapper:
    def __init__(self, s):
        self.s = s
    def accept(self):
        s_conn, address = self.s.accept()
        # set close-on-exec flag (subprocesses should not inherit it)
        set_close_on_exec(s_conn, True)
        return s_conn, address
    def __getattr__(self, attr):
        return getattr(self.s, attr)

def server_socket(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # set close-on-exec flag (subprocesses should not inherit it)
    set_close_on_exec(s, True)
    s.bind(('', port))
    s.listen(1)
    return ServerSocketWrapper(s)

class TCPServer(object):
    def __init__(self, port):
        self.s = server_socket(port)
        self.listener_classes = {}

    def join_event_loop(self, ev_loop):
        self.ev_loop = ev_loop
        ev_loop.register_listener(self)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.s.fileno()

    def register_listener_class(self, req_id, cls, **ctor_args):
        self.listener_classes[req_id] = dict(
            cls = cls,
            ctor_args = ctor_args
        )

    # when the event loop detects an event for us, this is 
    # what we will do: accept the tcp connection, read
    # the request and create the appropriate listener, 
    # and register this listener in the event loop.
    def handle_event(self, ts):
        conn_s, addr = self.s.accept()
        sock_file = SmartSocketFile(conn_s)
        req_id = Requests.read_id(sock_file)
        if req_id is None or req_id not in self.listener_classes:
            print 'Invalid request.'
            sock_file.close()
            return
        # create the appropriate listener given the req_id
        listener_info = self.listener_classes[req_id]
        cls = listener_info['cls']
        ctor_args = listener_info['ctor_args'].copy()
        ctor_args.update(dict(
                    sock_file = sock_file))
        listener = cls(**ctor_args)
        self.ev_loop.register_listener(listener)

    def close(self):
        self.s.close()

