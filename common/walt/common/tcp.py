import pickle
import socket

from walt.common.service import GenericServer, ServiceRequests
from walt.common.tools import set_close_on_exec

PICKLE_VERSION = 4  # from python 3.4
LISTEN_BACKLOG = 256


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

    def shutdown(self, mode):
        return self._s.shutdown(mode)

    def getpeername(self):
        return self._s.getpeername()

    def setsockopt(self, *args):
        return self._s.setsockopt(*args)

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
    s.listen(LISTEN_BACKLOG)
    # set close-on-exec flag (subprocesses should not inherit it)
    set_close_on_exec(s, True)
    return ServerSocketWrapper(s)


class TCPServer(GenericServer):
    def __init__(self, port):
        GenericServer.__init__(self)
        self._port = port

    def open_server_socket(self):
        return server_socket(self._port)

    # when the event loop detects an event for us, this is
    # what we will do: accept the tcp connection, read
    # the request and create the appropriate listener,
    # and register this listener in the event loop.
    def handle_server_socket_event(self, serv_s):
        conn_s, addr = serv_s.accept()
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
