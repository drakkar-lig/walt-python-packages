import socket
from fcntl import fcntl, F_GETFD, F_SETFD, FD_CLOEXEC

def udp_server_socket(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # set close-on-exec flag (subprocesses should not inherit it)
    fcntl(s.fileno(), F_SETFD, fcntl(s.fileno(), F_GETFD) | FD_CLOEXEC)
    s.bind(('', port))
    return s
