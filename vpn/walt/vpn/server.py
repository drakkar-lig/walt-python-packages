import os, socket, struct, cffi, subprocess, traceback, array
from time import time
from select import select
from pathlib import Path
from walt.vpn.tools import createtap, read_n, enable_debug, debug, readline_unbuffered
from walt.vpn.const import VPN_SOCK_PATH
from walt.vpn.ext._loops.lib import server_transmission_loop

# walt-vpn-server listens on a UNIX socket, and each client connects
# with two endpoint streams:
# * one transfering packet lengths
# * one transfering packet contents
# it has to:
# 1. accept the client endpoint streams
# 2. receive each stream stdin & stdout fds through ancilliary data
# 3. once both streams are connected, create a tap for this client
#    and add it to bridge walt-net
# 4. transmit data from the tap to the client streams stdout,
#    and transmit data from client streams stdin to the tap
#
# in order to keep the C code simple in walt.vpn.ext.loops.c,
# we manage clients (walt-vpn-endpoint) here in python code:
# - python code manages connection of a new client endpoint stream.
# - python code manages disconnection of a client endpoint stream.
# - python code ensures that:
#   * the tap fd of each client is a multiple of 8
#   * the lengths stdin of each client is tap_fd + 1
#   * the lengths stdout of each client is tap_fd + 2
#   * the lengths ctrl connection is tap_fd + 3
#   * the packets stdin of each client is tap_fd + 4
#   * the packets stdout of each client is tap_fd + 5
#   * the packets ctrl connection is tap_fd + 6
#   * tap_fd + 7 is unused
# - python code helps managing the max_fd integer necessary for select() calls:
#   * on_disconnect(tap_fd) returns new max_fd value
#   * on_connect() returns tap_fd value of new client when both streams are
#     accepted, 0 otherwise.
#
# note: having one tap per client allows walt-net bridging to work
# correctly, transmitting data to appropriate tap depending on mac
# addresses already detected in the previous traffic.

DEBUG = False

if DEBUG:
    enable_debug()

BRIDGE_INTF = "walt-net"
MAX_SETUP_MSG_LEN = 1024
WALT_VPN_STREAM_PROTO = 1

context = dict(
)

def fd_maskout(fd):
    fd_null = context['fd_null']
    os.dup2(fd_null, fd)

def fd_padding(fd_start, fd_end):
    for fd in range(fd_start, fd_end):
        fd_maskout(fd)

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
        s_serv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s_serv.bind(VPN_SOCK_PATH)
        sock_path.chmod(0o666)  # allow other users to connect
    else:
        print('systemd socket activation mode')
        # we know our socket fd is 3
        s_serv = socket.socket(fileno=3)
    return s_serv

def fd_offset(*args):
    return {
        ('tap',) : 0,
        ('lengths', 'stdin'): 1,
        ('lengths', 'stdout'): 2,
        ('lengths', 'ctrl'): 3,
        ('packets', 'stdin'): 4,
        ('packets', 'stdout'): 5,
        ('packets', 'ctrl'): 6,
    }[tuple(args)]

def fd_relocate(fd, fd_range_start, *args):
    new_fd = fd_range_start + fd_offset(*args)
    if new_fd != fd:
        os.dup2(fd, new_fd)
        os.close(fd)
    return new_fd

def on_connect():
    print('client stream connection')
    try:
        msg, fds = recv_fds(context['server_socket'], 3, 3)
        assert msg == b'FDS'
        assert len(fds) == 3
        stream_stdin, stream_stdout, stream_ctrl = fds[0], fds[1], fds[2]
        # send version (this will let walt-vpn-client know what we can do, should
        # this protocol evolve in the future)
        os.write(stream_stdout, f"VERSION {WALT_VPN_STREAM_PROTO}\n".encode('ASCII'))
        stream_info = {}
        while True:
            line = readline_unbuffered(stream_stdin)
            words = line.split()
            if words[0] == 'RUN':
                break
            if words[0] == 'SETUP':
                it = iter(words[1:])
                for attr in it:
                    value = next(it)
                    stream_info[attr] = value
        client_id = stream_info['CLIENT_ID']
        endpoint_mode = stream_info['ENDPOINT_MODE']
        if client_id not in context['clients_data']:
            # first stream connection for this client
            fd_range_start = stream_stdin
            context['clients_data'][client_id] = dict(fd_range_start = fd_range_start)
            fds_ready = set()
            for stream_type, fd in (('ctrl', stream_ctrl), ('stdout', stream_stdout), ('stdin', stream_stdin)):
                new_fd = fd_relocate(fd, fd_range_start, endpoint_mode, stream_type)
                fds_ready.add(new_fd)
                context['clients_data'][client_id][endpoint_mode + "_" + stream_type] = new_fd
            for fd in range(fd_range_start, fd_range_start + 8):
                if fd not in fds_ready:
                    fd_maskout(fd)
            return 0    # client not ready yet, wait for second stream
        else:
            # first stream already connected, this is the second
            fd_range_start = context['clients_data'][client_id]['fd_range_start']
            for stream_type, fd in (('ctrl', stream_ctrl), ('stdout', stream_stdout), ('stdin', stream_stdin)):
                new_fd = fd_relocate(fd, fd_range_start, endpoint_mode, stream_type)
                context['clients_data'][client_id][endpoint_mode + "_" + stream_type] = new_fd
            # create TAP
            tap_fd = fd_range_start + fd_offset('tap')
            os.close(tap_fd)    # we want the tap here
            tap, tap_name = createtap()
            assert tap.fileno() == tap_fd
            # bring it up, add it to bridge
            subprocess.check_call('ip link set up dev %(intf)s' % \
                                    dict(intf = tap_name), shell=True)
            subprocess.check_call('ip link set master ' + BRIDGE_INTF + ' dev ' + tap_name, shell=True)
            print('added ' + tap_name + ' to bridge ' + BRIDGE_INTF)
            # save python objects
            context['clients_data'][client_id]['tap'] = tap
            context['clients_per_tap'][tap_fd] = client_id
            return tap_fd
    except:
        traceback.print_exc()
        return -1

def on_disconnect(tap_fd):
    print('client disconnection')
    try:
        # close
        for offset in range(1, 8):
            os.close(tap_fd + offset)
        client_id = context['clients_per_tap'].pop(tap_fd)
        context['clients_data'][client_id]['tap'].close()
        del context['clients_data'][client_id]
        # return the new max fd
        if len(context['clients_data']) == 0:
            return context['server_socket'].fileno()
        else:
            max_tap_fd = max(context['clients_per_tap'].keys())
            return max_tap_fd - fd_offset('tap') + fd_offset('packets', 'stdin')
    except:
        traceback.print_exc()
        return -1

def run():
    # turn python callbacks into C callbacks
    ffi = cffi.FFI()
    cb_on_connect = ffi.callback('int (*func)()', on_connect)
    cb_on_disconnect = ffi.callback('int (*func)(int)', on_disconnect)
    # create listening socket
    s_serv = listen_socket()
    assert s_serv.fileno() == 3     # 0, 1, 2 for stdin, out, err
    fd_null = os.open(os.devnull, os.O_RDONLY)
    # save context
    context.update(
        fd_null = fd_null,
        server_socket = s_serv,
        clients_data = {},
        clients_per_tap = {}
    )
    # ensure next file descriptor will be 8
    fd_padding(fd_null + 1, 8)
    # start C loop
    server_transmission_loop(cb_on_connect, cb_on_disconnect)
