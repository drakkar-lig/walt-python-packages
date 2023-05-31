import array
import pickle
import secrets
import socket
from pathlib import Path

from walt.common.service import GenericServer, ServiceRequests
from walt.common.tools import set_close_on_exec


def send_msg_fds(sock, msg, fds, peer_addr):
    if len(fds) > 0:
        ancdata = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))]
    else:
        ancdata = []
    return sock.sendmsg([msg], ancdata, 0, peer_addr)


# Function from https://docs.python.org/3/library/socket.html#socket.socket.recvmsg
def recv_msg_fds(sock, msglen, maxfds):
    fds = array.array("i")  # Array of ints
    msg, ancdata, flags, emitter_addr = sock.recvmsg(
        msglen, socket.CMSG_LEN(maxfds * fds.itemsize)
    )
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
            # Append data, ignoring any truncated integers at the end.
            fds.frombytes(cmsg_data[: len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
    return msg, list(fds)


def bind_to_random_sockname(s):
    random_abstract_sockname = ("\0" + secrets.token_hex(4)).encode("ASCII")
    s.bind(random_abstract_sockname)


class Requests(ServiceRequests):
    REQ_FAKE_TFTP_GET_FD = 0


# since we are on a UNIX socket, we know the client is on the same
# machine thus it has the same walt software version, so no need
# to keep backward compatibility as in tcp.py.


class UnixServer(GenericServer):
    def __init__(self, sock_path):
        GenericServer.__init__(self)
        self.sock_path = Path(sock_path)

    def prepare(self, ev_loop):
        if self.sock_path.exists():
            self.sock_path.unlink()
        else:
            self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(str(self.sock_path))
        set_close_on_exec(s, True)
        self.s = s
        # allow only root to connect
        self.sock_path.chmod(0o600)
        self.join_event_loop(ev_loop)

    # when the event loop detects an event for us, this is
    # what we will do: read the request and create the appropriate
    # listener, and register this listener in the event loop.
    def handle_event(self, ts):
        msg, ancdata, flags, peer_addr = self.s.recvmsg(256)
        req_id, args, kwargs = pickle.loads(msg)
        listener = self.get_listener(req_id)
        if listener is not None:
            listener.run(self.s, peer_addr, *args, **kwargs)
        # even if there was an issue when running this listener,
        # the server itself should continue running
        return True
