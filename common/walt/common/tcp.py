import pickle
import socket

from walt.common.service import GenericServer, ServiceRequests
from walt.common.tools import set_close_on_exec

PICKLE_VERSION = 4  # from python 3.4


class Requests(ServiceRequests):
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
    REQ_VPN_NODE_IMAGE = 13
    REQ_NOTIFY_BOOTUP_STATUS = 14
    REQ_DEVICE_SHELL = 15
    REQ_TAR_FOR_IMAGE_BUILD = 16

    @staticmethod
    def read_id(stream):
        try:
            return Requests.get_id(stream.readline().decode("ascii").strip())
        except Exception:
            return None

    @staticmethod
    def send_id(stream, req_id):
        stream.write(b"%d\n" % req_id)
        stream.flush()


def read_pickle(stream):
    try:
        return pickle.load(stream)
    except Exception:
        return None


def write_pickle(obj, stream):
    pickle.dump(obj, stream, PICKLE_VERSION)
    stream.flush()


class RWSocketFile:
    def __init__(self, sock):
        self.sock = sock
        self.file_r = sock.makefile("rb", 0)
        self.file_w = sock.makefile("wb", 0)

    def shutdown(self, mode):
        return self.sock.shutdown(mode)

    def getpeername(self):
        return self.sock.getpeername()

    def setsockopt(self, *args):
        return self.sock.setsockopt(*args)

    def __getattr__(self, attr):
        if attr in ("write", "flush"):
            f = self.file_w
        else:
            f = self.file_r
        return getattr(f, attr)

    @property
    def closed(self):
        return self.file_r is None

    def close(self):
        if self.file_r is not None:
            self.file_r.close()
            self.file_r = None
        if self.file_w is not None:
            self.file_w.close()
            self.file_w = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def __del__(self):
        self.close()


def client_sock_file(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # set close-on-exec flag (subprocesses should not inherit it)
    set_close_on_exec(s, True)
    try:
        s.connect((host, port))
    except Exception:
        s.close()
        raise
    return RWSocketFile(s)


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
    s.bind(("", port))
    s.listen(1)
    # set close-on-exec flag (subprocesses should not inherit it)
    set_close_on_exec(s, True)
    return ServerSocketWrapper(s)


class TCPServer(GenericServer):
    def __init__(self, port):
        GenericServer.__init__(self)
        self._port = port

    def prepare(self, ev_loop):
        self.s = server_socket(self._port)
        self.join_event_loop(ev_loop)

    # when the event loop detects an event for us, this is
    # what we will do: accept the tcp connection, read
    # the request and create the appropriate listener,
    # and register this listener in the event loop.
    def handle_event(self, ts):
        conn_s, addr = self.s.accept()
        sock_file = RWSocketFile(conn_s)
        req_id = Requests.read_id(sock_file)
        listener = self.get_listener(req_id, sock_file=sock_file)
        if listener is None:
            sock_file.close()  # failed
        else:
            self.ev_loop.register_listener(listener)
        # even if there was an issue when starting this listener,
        # the server itself should continue running
        return True
