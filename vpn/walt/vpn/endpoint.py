import socket
from walt.vpn.const import VPN_SOCK_PATH
from walt.vpn.ext._loops.lib import endpoint_transmission_loop

def run():
    # connect to VPN server socket
    s_conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s_conn.connect(VPN_SOCK_PATH)
    s_fd = s_conn.fileno()
    endpoint_transmission_loop(s_fd)
