import os, socket, struct, cffi, subprocess, traceback, array
from time import time
from select import select
from pathlib import Path
from walt.vpn.tools import createtap, read_n, enable_debug, debug
from walt.vpn.const import VPN_SOCK_PATH, VPN_SOCK_BACKLOG
from walt.vpn.ext._loops.lib import server_transmission_loop

DEBUG = False

if DEBUG:
    enable_debug()

BRIDGE_INTF = "walt-net"

context = dict(
)

# Function from https://docs.python.org/3/library/socket.html#socket.socket.recvmsg
def recv_fds(sock, msglen, maxfds):
    fds = array.array("i")   # Array of ints
    msg, ancdata, flags, addr = sock.recvmsg(msglen, socket.CMSG_LEN(maxfds * fds.itemsize))
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if (cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS):
            # Append data, ignoring any truncated integers at the end.
            fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
    return msg, list(fds)

# prepare the VPN server socket
def listen_socket():
    listen_fds = os.environ.get('LISTEN_FDS')
    if listen_fds is None:
        print('standalone mode')
        # open the socket file ourselves
        sock_path = Path(VPN_SOCK_PATH)
        if sock_path.exists():
            sock_path.unlink()
        s_serv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s_serv.bind(VPN_SOCK_PATH)
        s_serv.listen(VPN_SOCK_BACKLOG)
        sock_path.chmod(0o666)  # allow other users to connect
    else:
        print('systemd socket activation mode')
        # we know our socket fd is 3
        s_serv = socket.socket(fileno=3)
    return s_serv

def on_connect():
    print('client connection')
    try:
        # create TAP
        tap, tap_name = createtap()
        tap_fd = tap.fileno()
        assert tap_fd & 1 == 0    # even number
        # bring it up, add it to bridge
        subprocess.check_call('ip link set up dev %(intf)s' % \
                                dict(intf = tap_name), shell=True)
        subprocess.check_call('ip link set master ' + BRIDGE_INTF + ' dev ' + tap_name, shell=True)
        print('added ' + tap_name + ' to bridge ' + BRIDGE_INTF)
        # accept the new client
        s_client, addr = context['server_socket'].accept()
        assert s_client.fileno() == tap_fd + 1
        # receive client stdin and stdout file descriptors
        msg, fds = recv_fds(s_client, 4, 2)
        assert msg == b'FDS\n'
        assert len(fds) == 2
        assert fds[0] == tap_fd + 2
        assert fds[1] == tap_fd + 3
        # save python objects
        context['clients_data'][tap_fd] = { 'tap': tap, 's_client': s_client }
        return tap_fd
    except:
        traceback.print_exc()
        return -1

def on_disconnect(tap_fd):
    print('client disconnection')
    try:
        # close
        os.close(tap_fd + 2)
        os.close(tap_fd + 3)
        client_data = context['clients_data'].pop(tap_fd)
        client_data['tap'].close()
        client_data['s_client'].shutdown(socket.SHUT_RDWR)
        client_data['s_client'].close()
        # return the new max fd
        if len(context['clients_data']) == 0:
            return context['server_socket'].fileno()
        else:
            max_tap_fd = max(context['clients_data'].keys())
            # client stdin fd is tap fd plus 2
            return max_tap_fd + 2
    except:
        traceback.print_exc()
        return -1

# walt-vpn-server listens on a UNIX socket, and for each client connecting,
# it has to:
# 1. create a tap for this client and add it to bridge walt-net
# 2. accept the client
# 3. receive client stdin & stdout fds through ancilliary data
# 4. transmit data from the tap to the client stdout, and transmit data
#    from client stdin to the tap
#
# in order to keep the C code simple in walt.vpn.ext.loops.c,
# we manage clients (walt-vpn-endpoint) here in python code:
# - python code manages connection of a new client endpoint.
# - python code manages disconnection of a client endpoint.
# - python code ensures that:
#   * the tap fd of each client endpoint is a multiple of 4
#   * the socket fd of each client endpoint is tap_fd + 1
#   * the stdin of each client endpoint is tap_fd + 2
#   * the stdout of each client endpoint is tap_fd + 3
# - python code helps managing the max_fd integer necessary for select() calls,
#   since on_disconnect(tap_fd) returns its new value
#
# note: having one tap per client allows walt-net bridging to work
# correctly, transmitting data to appropriate tap depending on mac
# addresses already detected in the previous traffic.

def run():
    # turn python callbacks into C callbacks
    ffi = cffi.FFI()
    cb_on_connect = ffi.callback('int (*func)()', on_connect)
    cb_on_disconnect = ffi.callback('int (*func)(int)', on_disconnect)
    # create listening socket
    s_serv = listen_socket()
    assert s_serv.fileno() == 3     # 0, 1, 2 for stdin, out, err
    # save context
    context.update(
        server_socket = s_serv,
        clients_data = {}
    )
    # start C loop
    server_transmission_loop(cb_on_connect, cb_on_disconnect)
