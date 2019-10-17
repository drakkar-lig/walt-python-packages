import os, socket, struct
import subprocess
from time import time
from select import select
from pathlib import Path
from walt.virtual.tools import createtap, read_n, enable_debug, debug
from walt.virtual.vpn.const import VPN_SOCK_PATH, VPN_SOCK_BACKLOG

DEBUG = False

if DEBUG:
    enable_debug()

BRIDGE_INTF = "walt-net"

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
        s_serv = socket.fromfd(3, socket.AF_UNIX, socket.SOCK_STREAM)
    return s_serv

def run():
    # Create TAP
    tap, tap_name = createtap()

    # Bring it up, add it to bridge
    subprocess.check_call('ip link set up dev %(intf)s' % \
                            dict(intf = tap_name), shell=True)
    subprocess.check_call('ip link set master ' + BRIDGE_INTF + ' dev ' + tap_name, shell=True)

    print('added ' + tap_name + ' to bridge ' + BRIDGE_INTF)

    s_serv = listen_socket()

    # start select loop
    # we will just:
    # * accept all clients that connect to /var/run/walt-vpn.sock
    # * transfer packets coming from a client to the tap interface
    # * transfer packets coming from the tap interface to all clients
    fds = [ s_serv, tap ]
    while True:
        r, w, e = select(fds, [], [])
        if len(r) == 0:
            break
        r_obj = r[0]
        num_peers = len(fds) - 2
        if r_obj == s_serv:
            s_client, addr = s_serv.accept()
            fds.append(s_client)
            continue
        if r_obj == tap:    # packet from tap
            packet = os.read(tap.fileno(), 8192)
            if len(packet) == 0:
                # unexpected, let's stop
                print(time(), 'short read on tap, exiting.')
                break
            if num_peers == 0:  # no-one is connected
                continue
            # encode packet length as 2 bytes
            encoded_packet_len = struct.pack('!H', len(packet))
            debug('transmitting packet of', len(packet), 'bytes from tap to', num_peers, 'peers')
        else:               # packet from a peer
            disconnected = False
            encoded_packet_len = read_n(r_obj.fileno(), 2)
            if len(encoded_packet_len) < 2:
                disconnected = True
            if disconnected is False:
                # decode 2 bytes of packet length
                packet_len = struct.unpack('!H', encoded_packet_len)[0]
                packet = read_n(r_obj.fileno(), packet_len)
                if len(packet) < packet_len:
                    disconnected = True
            if disconnected:
                print(time(), 'peer is probably disconnected!')
                fds.remove(r_obj)
                r_obj.close()
                continue
            debug('transmitting packet of', len(packet), 'bytes from a peer to tap and', num_peers-1, 'other peers')
        for w_obj in fds[1:]:
            if w_obj == r_obj:
                continue
            if w_obj == tap:
                os.write(w_obj.fileno(), packet)
            else:
                os.write(w_obj.fileno(), encoded_packet_len)
                os.write(w_obj.fileno(), packet)
