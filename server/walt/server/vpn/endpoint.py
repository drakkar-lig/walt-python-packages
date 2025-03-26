import os
import socket
import sys

from walt.common.unix import bind_to_random_sockname, recv_msg_fds
from walt.server.vpn.const import VPN_SOCK_PATH
from walt.server.ext._c_ext.lib import _vpn_endpoint_transmission_loop
from walt.server.tools import ip_in_walt_network


def run():
    orig_cmd = os.environ.get("SSH_ORIGINAL_COMMAND")
    # The client may specify argument "check-in-walt-net", in which case
    # we test if the client IP is in walt-net and just return "OK".
    # Getting here also means that authentication was ok, and the client
    # can ensure this server is the one it expects thanks to the host
    # keys it has saved.
    if orig_cmd == "check-in-walt-net":
        check_in_walt_net()
    # The tool walt-server-setup may also use argument "get-server-hostname"
    # to verify that the ssh entrypoint the user specified in the configuration
    # screen correctly redirects to this server.
    elif orig_cmd == "get-server-hostname":
        print(socket.getfqdn())
        sys.exit(0)  # success
    # Otherwise, we just start the real VPN process, which sets up a
    # TAP interface and forwards network packets back and forth between
    # this TAP interface and stdin/stdout.
    else:
        real_vpn_process()


def check_in_walt_net():
    ssh_client_info = os.environ.get("SSH_CLIENT")
    if ssh_client_info is None:
        print("FAILED -- SSH_CLIENT env variable is missing")
        sys.exit(1)
    client_ip = ssh_client_info.split()[0]
    if ip_in_walt_network(client_ip):
        print("OK")
        sys.exit(0)  # success
    else:
        print("FAILED -- NOT in walt network")
        sys.exit(1)


def real_vpn_process():
    # connect to VPN server socket
    s_conn = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    bind_to_random_sockname(s_conn)
    s_conn.connect(VPN_SOCK_PATH)
    # send hello message
    s_conn.send(b"HELLO")
    # receive the file descriptor of the tap interface walt-server-vpn
    # just created
    msg, fds = recv_msg_fds(s_conn, 256, 1)
    assert msg.startswith(b"HELLO")
    assert len(fds) == 1
    tap_fd = fds[0]
    # we are done with this socket
    s_conn.close()
    # run transmission loop
    _vpn_endpoint_transmission_loop(tap_fd)
    # close
    os.close(tap_fd)
