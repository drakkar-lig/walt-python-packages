import os
import pickle
import socket

import bottle
from gevent.fileobject import FileObject
from gevent.pywsgi import WSGIServer
from walt.common.unix import Requests, bind_to_random_sockname, recv_msg_fds
from walt.server.const import UNIX_SERVER_SOCK_PATH
from walt.server.tools import get_server_ip

WALT_HTTPD_PORT = 80

WELCOME_PAGE = """
<html>
<h2>WalT server HTTP service</h2>

Available sub-directories:
<ul>
  <li> <b>/boot</b> -- boot files to be retrieved by HTTP-capable bootloaders </li>
</ul>
</html>
"""

MAIN_DAEMON_SOCKET_TIMEOUT = 3


def fake_tftp_read(s_conn, ip, path):
    # send message
    req_id = Requests.REQ_FAKE_TFTP_GET_FD
    args = ()
    kwargs = dict(node_ip=ip, path=path)
    msg = req_id, args, kwargs
    s_conn.send(pickle.dumps(msg))
    # receive the response
    msg, fds = recv_msg_fds(s_conn, 256, 1)
    msg = pickle.loads(msg)
    # return result
    assert "status" in msg
    if msg["status"] == "OK":
        assert len(fds) == 1
        fd = fds[0]
        f = FileObject(fd, mode="rb")
        return "OK", f
    else:
        assert "error_msg" in msg
        return msg["error_msg"], None


def notify_systemd():
    if "NOTIFY_SOCKET" in os.environ:
        import sdnotify

        sdnotify.SystemdNotifier().notify("READY=1")


def get_socket():
    s_conn = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    bind_to_random_sockname(s_conn)
    s_conn.settimeout(MAIN_DAEMON_SOCKET_TIMEOUT)
    s_conn.connect(UNIX_SERVER_SOCK_PATH)
    return s_conn


# this will hold the socket to walt-server-daemon
s_conn = None


def run():
    # instanciate web app
    app = bottle.Bottle()

    @app.route("/")
    @app.route("/index.html")
    def welcome():
        return WELCOME_PAGE

    @app.route("/boot/<path:path>")
    def serve(path):
        global s_conn
        # for a virtual node actually running on the server,
        # the IP address of the socket peer does not match
        # the node IP. For this case, URL may indicate the
        # node_ip as an URL parameter.
        node_ip = bottle.request.query.get("node_ip")
        if node_ip is None:
            node_ip = bottle.request.environ.get("REMOTE_ADDR")
            node_ip = node_ip.lstrip("::ffff:")
        for i in range(2):
            if s_conn is None:
                s_conn = get_socket()
            try:
                status, f = fake_tftp_read(s_conn, node_ip, "/" + path)
            except OSError:
                if i == 0:
                    # try to re-init the socket to walt-server-daemon
                    s_conn.close()
                    s_conn = None
                    continue
                else:
                    raise
        if status == "OK":
            return f
        elif status == "NO SUCH FILE":
            return bottle.HTTPError(404, "No such file.")
        else:
            return bottle.HTTPError(400, status)

    # run web app
    server = WSGIServer((get_server_ip(), WALT_HTTPD_PORT), app)
    notify_systemd()
    server.serve_forever()
