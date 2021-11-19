import socket, array, secrets, os
from walt.vpn.const import VPN_SOCK_PATH
from walt.vpn.ext._loops.lib import endpoint_transmission_loop

# Function from https://docs.python.org/3/library/socket.html#socket.socket.recvmsg
def recv_fds(sock, msglen, maxfds):
    fds = array.array("i")   # Array of ints
    msg, ancdata, flags, emitter_addr = sock.recvmsg(msglen, socket.CMSG_LEN(maxfds * fds.itemsize))
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if (cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS):
            # Append data, ignoring any truncated integers at the end.
            fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
    return msg, list(fds)

def random_abstract_sockname():
    return ('\0' + secrets.token_hex(4)).encode('ASCII')

def run():
    # connect to VPN server socket
    s_conn = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s_conn.bind(random_abstract_sockname())
    s_conn.connect(VPN_SOCK_PATH)
    # send hello message
    s_conn.send(b'HELLO')
    # receive the file descriptor of the tap interface walt-vpn-server
    # just created
    msg, fds = recv_fds(s_conn, 256, 1)
    assert msg.startswith(b'HELLO')
    assert len(fds) == 1
    tap_fd = fds[0]
    # we are done with this socket
    s_conn.close()
    # run transmission loop
    endpoint_transmission_loop(tap_fd)
    # close
    os.close(tap_fd)
