import os
import socket
import subprocess
import traceback
from pathlib import Path
from shutil import chown

from walt.common.unix import send_msg_fds
from walt.vpn.const import VPN_SOCK_PATH
from walt.vpn.tools import createtap

BRIDGE_INTF = "walt-net"


# prepare the VPN server socket
def listen_socket():
    listen_fds = os.environ.get("LISTEN_FDS")
    sock_path = Path(VPN_SOCK_PATH)
    if listen_fds is None:
        print("standalone mode")
        # open the socket file ourselves
        if sock_path.exists():
            sock_path.unlink()
        s_serv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s_serv.bind(VPN_SOCK_PATH)
        # allow only walt-vpn user to connect
        chown(str(sock_path), "walt-vpn")
        sock_path.chmod(0o600)
    else:
        print("systemd socket activation mode")
        # we know our socket fd is 3
        s_serv = socket.socket(fileno=3)
    return s_serv


def on_message(s_serv, msg, ancdata, flags, peer_addr):
    print("client connection")
    tap_fd = -1
    try:
        # read client hello message
        assert peer_addr is not None  # endpoint must bind its socket
        assert msg.startswith(b"HELLO")
        # create TAP
        tap, tap_name = createtap()
        tap_fd = tap.fileno()
        # bring it up, add it to bridge
        subprocess.check_call(
            "ip link set up dev %(intf)s" % dict(intf=tap_name), shell=True
        )
        subprocess.check_call(
            "ip link set master " + BRIDGE_INTF + " dev " + tap_name, shell=True
        )
        print("added " + tap_name + " to bridge " + BRIDGE_INTF)
        # send tap filedescriptor to the new client
        send_msg_fds(s_serv, b"HELLO", (tap_fd,), peer_addr)
    except Exception:
        traceback.print_exc()
        print("continuing...")
    finally:
        # even if everything worked, close tap fd
        # (since endpoint will manage it itself)
        if tap_fd != -1:
            os.close(tap_fd)


# walt-vpn-server listens on a UNIX socket, and for each endpoint connecting,
# it has to:
# 1. create a tap for this endpoint and add it to bridge walt-net
# 2. send file descriptor of the tap to the endpoint
#
# note: having one tap per client endpoint allows walt-net bridging to work
# correctly, transmitting data to appropriate tap depending on mac
# addresses already detected in the previous traffic.


def run():
    # create listening socket
    s_serv = listen_socket()
    # start loop
    while True:
        msg, ancdata, flags, peer_addr = s_serv.recvmsg(256)
        on_message(s_serv, msg, ancdata, flags, peer_addr)
