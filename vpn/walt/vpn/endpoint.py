import os
import socket

from walt.common.unix import bind_to_random_sockname, recv_msg_fds
from walt.vpn.const import VPN_SOCK_PATH
from walt.vpn.ext._loops.lib import endpoint_transmission_loop


def run():
    # connect to VPN server socket
    s_conn = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    bind_to_random_sockname(s_conn)
    s_conn.connect(VPN_SOCK_PATH)
    # send hello message
    s_conn.send(b"HELLO")
    # receive the file descriptor of the tap interface walt-vpn-server
    # just created
    msg, fds = recv_msg_fds(s_conn, 256, 1)
    assert msg.startswith(b"HELLO")
    assert len(fds) == 1
    tap_fd = fds[0]
    # we are done with this socket
    s_conn.close()
    # run transmission loop
    endpoint_transmission_loop(tap_fd)
    # close
    os.close(tap_fd)
