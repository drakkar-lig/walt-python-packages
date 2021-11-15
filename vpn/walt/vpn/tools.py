import os, sys, socket
from subprocess import check_call
from walt.vpn.const import L2TP_LOOPBACK_UDP_SPORT, L2TP_LOOPBACK_UDP_DPORT, \
                           BRIDGE_INTF, L2TP_INTERFACE_MTU

# create an L2TP tunnel and interface
def create_l2tp_tunnel(tunnel_id, peer_tunnel_id):
    check_call(f'ip l2tp add tunnel \
                    tunnel_id {tunnel_id} peer_tunnel_id {peer_tunnel_id} \
                    encap udp local 127.0.0.1 remote 127.0.0.1 \
                    udp_sport {L2TP_LOOPBACK_UDP_SPORT} \
                    udp_dport {L2TP_LOOPBACK_UDP_DPORT}', shell=True)

def remove_l2tp_tunnel(tunnel_id):
    check_call(f'ip l2tp del tunnel \
                    tunnel_id {tunnel_id}', shell=True)

def create_l2tp_interface(tunnel_id, session_id, peer_session_id):
    ifname = f"walt-l2tp-{session_id}"
    check_call(f'ip l2tp add session \
                    name {ifname} \
                    tunnel_id {tunnel_id} \
                    session_id {session_id} \
                    peer_session_id {peer_session_id}', shell=True)
    check_call(f'ip link set \
                    mtu {L2TP_INTERFACE_MTU} \
                    master {BRIDGE_INTF} \
                    up \
                    dev {ifname}', shell=True)
    print(f'added {ifname} to bridge {BRIDGE_INTF}')
    return ifname

def remove_l2tp_interface(tunnel_id, session_id):
    check_call(f'ip l2tp del session \
                    tunnel_id {tunnel_id} \
                    session_id {session_id}', shell=True)

def create_l2tp_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # kernel will send us L2TP packets to be forwarded over the ssh tunnel
    # on this UDP port
    s.bind(('127.0.0.1', L2TP_LOOPBACK_UDP_DPORT))
    # we will send packets coming from the ssh tunnel to the kernel by
    # using this UDP port
    s.connect(('127.0.0.1', L2TP_LOOPBACK_UDP_SPORT))
    return s

def read_n(fd, n):
    buf = b''
    while len(buf) < n:
        chunk = os.read(fd, n - len(buf))
        if len(chunk) == 0:
            # short read!
            break
        buf += chunk
    return buf

def readline_unbuffered(fd):
    line = b''
    while True:
        c = os.read(fd, 1)
        if c == b'\n':
            break
        if c == b'':
            raise EOFError
        line += c
    return line.decode("ASCII")

DEBUG_OUT = None

def enable_debug(out = sys.stdout):
    global DEBUG_OUT
    DEBUG_OUT = out

def debug(*args):
    if DEBUG_OUT is not None:
        print(time(), *args, file=DEBUG_OUT)
        DEBUG_OUT.flush()
