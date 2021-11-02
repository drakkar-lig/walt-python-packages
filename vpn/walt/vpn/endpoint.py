import socket, array
from walt.vpn.const import VPN_SOCK_PATH
from walt.vpn.ext._loops.lib import endpoint_transmission_loop

def send_fds(sock, msg, fds):
    return sock.sendmsg([msg], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))])

def run():
    # connect to VPN server socket
    s_conn = socket.socket(family = socket.AF_UNIX)
    s_conn.connect(VPN_SOCK_PATH)
    s_fd = s_conn.fileno()
    # send stdin and stdout file-descriptors to the UNIX socket
    send_fds(s_conn, b'FDS\n', (0,1))
    # let the server work, just catch errors
    endpoint_transmission_loop(s_fd)
    # close
    s_conn.shutdown(socket.SHUT_RDWR)
    s_conn.close()
