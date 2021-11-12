import os, socket, struct, cffi, traceback, array, atexit
from time import time
from select import select
from pathlib import Path
from subprocess import check_call
from walt.vpn.tools import read_n, enable_debug, debug, readline_unbuffered,               \
     create_l2tp_tunnel, remove_l2tp_tunnel, create_l2tp_interface, remove_l2tp_interface, \
     create_l2tp_socket
from walt.vpn.const import VPN_SOCK_PATH, L2TP_SERVER_TUNNEL_ID, L2TP_CLIENT_TUNNEL_ID
from walt.vpn.ext._loops.lib import server_transmission_loop

# walt-vpn-server listens on a UNIX socket, and each client connects
# with two endpoint streams:
# * one transfering packet lengths
# * one transfering packet contents
# it has to:
# 1. accept the client endpoint streams
# 2. receive each stream stdin & stdout fds through ancilliary data
# 3. once both streams are connected, create an L2TP interface for
#    this client and add it to bridge walt-net
# 4. transmit data from the L2TP interface to the client streams stdout,
#    and transmit data from client streams stdin to the L2TP interface
#
# This code avoids the use of TAP interfaces because interaction with
# TAP interfaces is not efficient (single packet reads and writes).
# Instead, we use L2TP.
#
# Interaction with the L2TP interfaces (step 4) is not straightforward.
# Since we transfer packets through a SSH connection, we obviously do
# *not* create  a direct L2TP tunnel between the client and the server.
# Instead, on each side (client and server), we create an L2TP tunnel
# on the loopback interface. The kernel believes it is communicating with
# the remote peer, whilst it is actually communicating with a userspace
# component (walt-vpn-client and walt-vpn-server, respectively). This
# component transmits and receives L2TP packets over the SSH connexion.
#
# See below for a diagram indicating how this works on server side:
#
#                                  ┌────────────┐
#                           ┌──────►C2 L2TP intf├─────┐  ┌─────────────┐
#                           │      └────────────┘     │  │             │
#                           │                         └──┤   walt-net  │
#                           │      ┌────────────┐        │    bridge   │
#                           │  ┌───►C1 L2TP intf├────────┤             │
#                           │  │   └────────────┘        └──┬───┬───┬──┘
#                           │  │                            │   │   │
#                           │  │   ┌────────────┐
#                           │  │   │            │
#                           │  └───►    L2TP   A├──────┐
#        kernel             │      │   tunnel   │      │
#      components           └──────►           A◄──┐   │
#                                  └────────────┘  │   │
#   ---------------------------------------------- │ - │ --------------
#                                  ┌────────────┐  │   │
#                                  │   WALT     │ xxxxxxx  UDP
#                                  │   VPN      │ xxxxxxx Socket
#                                  │  Server    │  │   │
#                                  │            │  │   │
#   ───────────────────────────────│            │  │   │
#               C1 SSH connection  │            │  │   │
#                            ──────┼────┬──────B►──┘   │
#                                  │    │ (C)   │      │
#                            ◄─────┼────┼──┬───B◄──────┘
#                                  │    │  │    │
#   ───────────────────────────────│    │  │    │
#                                  │    │  │    │
#                                  │    │  │    │
#   ───────────────────────────────│    │  │    │
#               C2 SSH connection  │    │  │    │
#                            ──────┼────┘  │    │
#                                  │       │    │
#                            ◄─────┼───────┘    │
#                                  │            │
#   ───────────────────────────────│            │
#                                  │            │
#                                  └────────────┘
#
# Notes:
# - the L2TP tunnel running on the loopback interface is defined by:
#   * its source UDP port named A on the diagram
#   * its destination UDP port named B on the diagram
# - whatever the client (C1 or C2 on the diagram), all L2TP packets
#   can be forwarded from the SSH connection to the UDP socket
# - when WALT VPN server receives an L2TP packet from the UDP socket,
#   it must check the L2TP session ID written in the L2TP packet header
#   in order to transmit it to the appropriate SSH connection (this
#   process occurs at point C on the diagram).
#
# This diagram only shows one ssh connection per client. In reality,
# we have two streams per client, one holding packet lengths
# information and one holding packet contents. We expect this to
# further evolve in the future to allow multiple packet streams per
# client, allowing to overcome the possible bottleneck of single-CPU
# SSH encryption.
#
# in order to keep the C code simple in walt/vpn/ext/loops.c,
# we manage clients streams (walt-vpn-endpoint) here in python code:
# - python code manages connection of a new client endpoint stream.
# - python code manages disconnection of a client endpoint stream.
# - python code ensures that:
#   * the range of file descriptors for each client starts at
#     a multiple of 8 (called fd_range_start)
#   * the lengths stdin of each client is fd_range_start + 0
#   * the lengths stdout of each client is fd_range_start + 1
#   * the lengths ctrl connection is fd_range_start + 2
#   * the packets stdin of each client is fd_range_start + 3
#   * the packets stdout of each client is fd_range_start + 4
#   * the packets ctrl connection is fd_range_start + 5
#   * fd_range_start + 6 and 7 are unused
# - python code helps managing the max_fd integer necessary for select() calls:
#   * on_disconnect(fd_range_start) returns new max_fd value
#   * on_connect() returns fd_range_start value of new client when both streams
#     are accepted, 0 otherwise.
#
# note: having one virtual interface (L2TP) per client allows walt-net bridging
# to work correctly, transmitting data to appropriate interface depending on mac
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
        ('lengths', 'stdin'): 0,
        ('lengths', 'stdout'): 1,
        ('lengths', 'ctrl'): 2,
        ('packets', 'stdin'): 3,
        ('packets', 'stdout'): 4,
        ('packets', 'ctrl'): 5,
    }[tuple(args)]

def fd_relocate(fd, fd_range_start, *args):
    new_fd = fd_range_start + fd_offset(*args)
    if new_fd != fd:
        os.dup2(fd, new_fd)
        os.close(fd)
    return new_fd

def send_env(fd, fd_range_start):
    os.write(fd, (f"ENV L2TP_SERVER_TUNNEL_ID {L2TP_SERVER_TUNNEL_ID}" + \
                  f"    L2TP_CLIENT_TUNNEL_ID {L2TP_CLIENT_TUNNEL_ID}" + \
                  f"    L2TP_SERVER_SESSION_ID {fd_range_start}" + \
                  f"    L2TP_CLIENT_SESSION_ID {fd_range_start}" + \
                   "\n").encode('ASCII'))

def create_virtual_interface(fd_range_start):
    # create L2TP interface
    session_id, peer_session_id = fd_range_start, fd_range_start
    ifname = create_l2tp_interface(L2TP_SERVER_TUNNEL_ID, session_id, peer_session_id)
    # bring it up, add it to bridge
    check_call(f'ip link set up dev {ifname}', shell=True)
    check_call(f'ip link set master {BRIDGE_INTF} dev {ifname}', shell=True)
    print(f'added {ifname} to bridge {BRIDGE_INTF}')
    return ifname

def remove_virtual_interface(fd_range_start):
    remove_l2tp_interface(L2TP_SERVER_TUNNEL_ID, fd_range_start)

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
            context['clients_data'][client_id] = dict(
                fd_range_start = fd_range_start
            )
            send_env(stream_stdout, fd_range_start)
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
            send_env(stream_stdout, fd_range_start)
            for stream_type, fd in (('ctrl', stream_ctrl), ('stdout', stream_stdout), ('stdin', stream_stdin)):
                new_fd = fd_relocate(fd, fd_range_start, endpoint_mode, stream_type)
                context['clients_data'][client_id][endpoint_mode + "_" + stream_type] = new_fd
            # create L2TP interface
            ifname = create_virtual_interface(fd_range_start)
            # save python objects
            context['clients_data'][client_id]['l2tp_ifname'] = ifname
            context['clients_per_fd'][fd_range_start] = client_id
            return fd_range_start
    except:
        traceback.print_exc()
        return -1

def on_disconnect(fd_range_start):
    print('client disconnection')
    try:
        # close
        for offset in range(8):
            os.close(fd_range_start + offset)
        client_id = context['clients_per_fd'].pop(fd_range_start)
        remove_virtual_interface(fd_range_start)
        del context['clients_data'][client_id]
        # return the new max fd
        if len(context['clients_data']) == 0:
            return context['l2tp_socket'].fileno()
        else:
            max_fd_range_start = max(context['clients_per_fd'].keys())
            return max_fd_range_start + fd_offset('packets', 'stdin')
    except:
        traceback.print_exc()
        return -1

def cleanup():
    print('cleaning up...')
    for fd_range_start in tuple(context['clients_per_fd'].keys()):
        try:
            on_disconnect(fd_range_start)
        except:
            traceback.print_exc()
            print('trying to continue cleanup...')
    context['l2tp_socket'].close()
    remove_l2tp_tunnel(L2TP_SERVER_TUNNEL_ID)

def run():
    # turn python callbacks into C callbacks
    ffi = cffi.FFI()
    cb_on_connect = ffi.callback('int (*func)()', on_connect)
    cb_on_disconnect = ffi.callback('int (*func)(int)', on_disconnect)
    # create listening socket
    s_serv = listen_socket()
    assert s_serv.fileno() == 3     # 0, 1, 2 for stdin, out, err
    # create L2TP tunnel
    tunnel_id, peer_tunnel_id = L2TP_SERVER_TUNNEL_ID, L2TP_CLIENT_TUNNEL_ID
    create_l2tp_tunnel(tunnel_id, peer_tunnel_id)
    # create L2TP UDP socket
    l2tp_socket = create_l2tp_socket()
    assert l2tp_socket.fileno() == 4
    fd_null = os.open(os.devnull, os.O_RDONLY)
    # save context
    context.update(
        fd_null = fd_null,
        server_socket = s_serv,
        l2tp_socket = l2tp_socket,
        clients_data = {},
        clients_per_fd = {}
    )
    # ensure next file descriptor will be 8
    fd_padding(fd_null + 1, 8)
    # handle cleanup on exit
    atexit.register(cleanup)
    # start C loop
    server_transmission_loop(cb_on_connect, cb_on_disconnect)
