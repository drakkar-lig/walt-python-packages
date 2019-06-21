import os, socket
from select import select
from pathlib import Path
from walt.virtual.vpn.const import VPN_SOCK_PATH

def run():
    # connect to VPN server socket
    s_conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s_conn.connect(VPN_SOCK_PATH)
    s_fd = s_conn.fileno()

    # start select loop
    # we will just:
    # * transfer packets coming from stdin to s_conn
    # * transfer packets coming from s_conn to stdin
    fds = [ s_fd, 0 ]
    while True:
        r, w, e = select(fds, [], [])
        if len(r) == 0:
            break
        r_fd = r[0]
        if r_fd == s_fd:
            w_fd = 1       # vpn socket -> stdout
        else:
            w_fd = s_fd    # stdin -> vpn socket
        packet = os.read(r_fd, 2048)
        if len(packet) == 0:
            break
        os.write(w_fd, packet)
