import os, socket
from time import time
from select import select
from pathlib import Path
from walt.virtual.tools import enable_debug, debug
from walt.virtual.vpn.const import VPN_SOCK_PATH

DEBUG = False

if DEBUG:
    log = open('/tmp/vpn-endpoint.log', 'w')
    enable_debug(log)

def run():
    # connect to VPN server socket
    s_conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s_conn.connect(VPN_SOCK_PATH)
    s_fd = s_conn.fileno()

    # start select loop
    # we will just:
    # * transfer bytes coming from stdin to s_conn
    # * transfer bytes coming from s_conn to stdin
    fds = [ s_fd, 0 ]
    while True:
        r, w, e = select(fds, [], [])
        if len(r) == 0:
            break
        r_fd = r[0]
        buf = os.read(r_fd, 8192)
        if len(buf) == 0:
            break
        if r_fd == s_fd:
            debug('writing', len(buf), 'bytes to peer')
            w_fd = 1       # vpn socket -> stdout
        else:
            debug('writing', len(buf), 'bytes to unix socket')
            w_fd = s_fd    # stdin -> vpn socket
        os.write(w_fd, buf)
