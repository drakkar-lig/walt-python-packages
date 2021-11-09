import socket, array, os
from walt.vpn.const import VPN_SOCK_PATH

def send_fds(sock, msg, fds):
    return sock.sendmsg([msg], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))])

def run():
    # create ctrl pipe
    ctrl_r, ctrl_w = os.pipe()
    # connect to VPN server socket
    s_conn = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s_conn.connect(VPN_SOCK_PATH)
    # send stdin & stdout file-descriptors
    send_fds(s_conn, b'FDS', (0,1,ctrl_w))
    # close things we do not need
    s_conn.close()
    os.close(ctrl_w)
    # wait for ctrl pipe termination
    # (means walt-vpn-server ended this client connection)
    os.read(ctrl_r, 1)
