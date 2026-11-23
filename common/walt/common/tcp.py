import pickle
import socket
from time import time

from walt.common.service import GenericServer, ServiceRequests
from walt.common.tools import set_close_on_exec

PICKLE_VERSION = 4  # from python 3.4
LISTEN_BACKLOG = 256

# A new connection must send its request id within NEW_CONN_REQ_ID_TIMEOUT
# seconds, otherwise it is closed. And when the server reads the first line
# of a request (e.g., the request id), the end of the line must arrive within
# FIRST_LINE_READ_TIMEOUT seconds. This prevents a client which connects and
# then gets stuck (e.g., a node which lost its root filesystem) from blocking
# the server process.
NEW_CONN_REQ_ID_TIMEOUT = 30
FIRST_LINE_READ_TIMEOUT = 2


# Send a keepalive probe every TCP_KEEPALIVE_IDLE_TIMEOUT seconds
# unless one of them gets no response.
# In this case send up to TCP_KEEPALIVE_FAILED_COUNT probes
# with an interval of TCP_KEEPALIVE_PROBE_INTERVAL, and if all
# probes fail consider the connection is lost.

TCP_KEEPALIVE_IDLE_TIMEOUT = 15
TCP_KEEPALIVE_PROBE_INTERVAL = 2
TCP_KEEPALIVE_FAILED_COUNT = 5


def set_tcp_keepalive(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    sock.setsockopt(socket.IPPROTO_TCP,
                    socket.TCP_KEEPIDLE,
                    TCP_KEEPALIVE_IDLE_TIMEOUT)
    sock.setsockopt(socket.IPPROTO_TCP,
                    socket.TCP_KEEPINTVL,
                    TCP_KEEPALIVE_PROBE_INTERVAL)
    sock.setsockopt(socket.IPPROTO_TCP,
                    socket.TCP_KEEPCNT,
                    TCP_KEEPALIVE_FAILED_COUNT)


def set_sock_reuseaddr(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)


def set_tcp_nodelay(sock):
    # disable Nagle
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


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
    REQ_NODE_NET_SERVICE = 14
    REQ_DEVICE_SHELL = 15
    REQ_TAR_FOR_IMAGE_BUILD = 16
    REQ_FETCH_NODE_CONFIG = 17
    REQ_CLOCK_SYNC = 18

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


class MyPickle:

    @staticmethod
    def dump(obj, file, protocol=None, **kwargs):
        pickle.dump(obj, file, PICKLE_VERSION, **kwargs)
        file.flush()

    @staticmethod
    def dumps(obj, protocol=None, **kwargs):
        return pickle.dumps(obj, PICKLE_VERSION, **kwargs)

    @staticmethod
    def load(file, **kwargs):
        changed_pickle_mode = False
        if isinstance(file, RWSocketFile) and not file.pickle_mode:
            changed_pickle_mode = True
            file.pickle_mode = True
        obj = pickle.load(file)
        if changed_pickle_mode:  # revert
            file.pickle_mode = False
        return obj

    @staticmethod
    def loads(data, **kwargs):
        return pickle.loads(data, **kwargs)


write_pickle = MyPickle.dump
read_pickle = MyPickle.load


# Using sock.makefile("rwb", 0) could work to some extent,
# but pickle does not handle partial reads, so we would get
# "pickle data was truncated" errors when receiving large
# pickled objects over the network.
# And using io.BufferredReader(sock.makefile("rwb", 0))
# would take care of this problem but it would cause other
# problems with the event loop (bufferring could prevent
# the event loop to detect new data).
# So we create our own unbuffered class with a special pickle mode
# which takes care of reading all requested bytes.
class RWSocketFile:
    def __init__(self, sock):
        self._s = sock
        self.pickle_mode = False
        # we only use the makefile() approach for readline()
        # which would be costly regarding trackexec if implemented here
        # as a loop reading 1 char at a time.
        self._readline_f = self._s.makefile("rb", 0)
        self.readline = self._readline_f.readline

    @property
    def sock(self):
        return self._s

    def shutdown(self, mode):
        return self._s.shutdown(mode)

    def getpeername(self):
        return self._s.getpeername()

    def set_keepalive(self):
        set_tcp_keepalive(self._s)

    def set_nodelay(self):
        set_tcp_nodelay(self._s)

    def fileno(self):
        return self._s.fileno()

    def __getattr__(self, attr):
        print(f"UNKNOWN __getattr__ {attr}")
        raise NotImplementedError

    def peek(self, size=0):
        return b""  # there is no buffering

    def read(self, size=None):
        # reading 1 char is a frequent pattern so we optimize
        # this path to reduce trackexec load.
        # (in this specific case the mode has no impact)
        if size == 1:
            return self._s.recv(1)
        # general case
        if self.pickle_mode:
            #print(f"full-read {size}")
            msg = b""
            if size is None:
                # read all
                while True:
                    chunk = self._s.recv(8192)
                    if len(chunk) == 0:
                        break
                    msg += chunk
            else:
                # read <size> bytes
                while size > 0:
                    chunk = self._s.recv(size)
                    if len(chunk) == 0:
                        break
                    size -= len(chunk)
                    msg += chunk
            return msg
        else:
            if size is None:
                size = -1
            return self.read1(size)

    def read1(self, size=-1):
        #print(f"read1 {size}")
        if size == 0:
            return b""
        if size == -1:
            size = 8192
        return self._s.recv(size)

    def readinto(self, b):
        #print(f"readinto {len(b)}")
        msg = self.read(len(b))
        b[:] = msg
        return len(b)

    def write(self, msg):
        self._s.sendall(msg)
        return len(msg)

    def flush(self):
        pass    # there is no buffering

    @property
    def closed(self):
        return self._s is None

    def close(self):
        if self._s is not None:
            self._readline_f.close()
            self._s.close()
            self._s = None

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
    sock_file = RWSocketFile(s)
    sock_file.set_keepalive()
    return sock_file


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
    set_sock_reuseaddr(s)
    s.bind(("", port))
    s.listen(LISTEN_BACKLOG)
    # set close-on-exec flag (subprocesses should not inherit it)
    set_close_on_exec(s, True)
    return ServerSocketWrapper(s)


def read_first_line(sock_file):
    # read a line, with a timeout (see FIRST_LINE_READ_TIMEOUT).
    # this raises an exception (e.g., TimeoutError) on failure.
    sock = sock_file.sock
    sock.settimeout(FIRST_LINE_READ_TIMEOUT)
    try:
        return sock_file.readline()
    finally:
        sock.settimeout(None)


class ListenerWrapper:
    """Event loop listener of a new TCP connection.

    It first reads the request id, only when the event loop detects incoming
    data, and with a timeout (see NEW_CONN_REQ_ID_TIMEOUT and
    FIRST_LINE_READ_TIMEOUT). Then it creates the listener of the request,
    and passes the next events to it.
    """

    def __init__(self, server, sock_file):
        self.server = server
        self.sock_file = sock_file
        self.listener = None
        self.closed = False

    def start(self):
        ev_loop = self.server.ev_loop
        ev_loop.register_listener(self.sock_file, self)
        ev_loop.plan_event(time() + NEW_CONN_REQ_ID_TIMEOUT,
                           callback=self.on_timeout)

    @property
    def allow_reordering(self):
        return getattr(self.listener, "allow_reordering", False)

    def handle_event(self, ts):
        if self.listener is not None:
            return self.listener.handle_event(ts)
        try:
            req_id = Requests.get_id(
                    read_first_line(self.sock_file).decode("ascii").strip())
        except Exception:
            req_id = None
        self.listener = self.server.get_listener(
                req_id, sock_file=self.sock_file)
        # if None, the event loop will close the connection
        return self.listener is not None

    def on_timeout(self):
        # close the connection if the request id was not received
        if self.listener is None and not self.closed:
            self.server.ev_loop.remove_listener(self)

    def close(self):
        self.closed = True
        if self.listener is not None:
            self.listener.close()


class TCPServer(GenericServer):
    def __init__(self, port):
        GenericServer.__init__(self)
        self._port = port

    def open_server_socket(self):
        return server_socket(self._port)

    # when the event loop detects an event for us, this is
    # what we will do: accept the tcp connection, and register a
    # ListenerWrapper in the event loop; it will read the request
    # id when it arrives (without blocking the event loop meanwhile),
    # and then create the appropriate listener.
    def handle_server_socket_event(self, serv_s):
        conn_s, addr = serv_s.accept()
        sock_file = RWSocketFile(conn_s)
        sock_file.set_keepalive()
        ListenerWrapper(self, sock_file).start()
        # the server itself should continue running
        return True
