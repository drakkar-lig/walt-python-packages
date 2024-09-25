import os
import json
import socket

import bottle
from gevent.fileobject import FileObject
from gevent.pywsgi import WSGIServer
from time import time
from walt.common.apilink import ServerAPILink
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import Requests as TcpRequests
from walt.common.tcp import MyPickle as pickle, client_sock_file
from walt.common.unix import Requests as UnixRequests
from walt.common.unix import bind_to_random_sockname, recv_msg_fds
from walt.server.const import UNIX_SERVER_SOCK_PATH
from walt.server.tools import np_recarray_to_tuple_of_dicts, convert_query_param_value
from pkg_resources import resource_filename

WALT_HTTPD_PORT = 80

WELCOME_PAGE = """
<html>
<h2>WalT server HTTP service</h2>

Available sub-directories:
<ul>
  <li> <b><a href="/doc">/doc</a></b> -- WalT documentation </li>
  <li> <b><a href="/api">/api</a></b> -- WalT web API</li>
  <li> <b>/boot</b> -- boot files to be retrieved by HTTP-capable node bootloaders </li>
</ul>
</html>
"""

API_PAGE = """
<html>
<h2>WalT web API</h2>

WalT provides the following web API entrypoints:
<ul>
  <li> <b><a href="/api/v1/nodes">/api/v1/nodes</a></b> </li>
  <li> <b><a href="/api/v1/images">/api/v1/images</a></b> </li>
  <li> <b>/api/v1/logs</b> (no web-link here, because some query parameters are mandatory!) </li>
</ul>

Checkout <a href="/doc/web-api.html">the web API documentation</a> for more info.
</html>
"""

MAIN_DAEMON_SOCKET_TIMEOUT = 3
HTML_DOC_DIR = resource_filename("walt.doc", "html")

WALT_T0 = 1340000000  # Epoch timestamp corresponding to some time in june 2012


def fake_tftp_read(s_conn, ip, path):
    # send message
    req_id = UnixRequests.REQ_FAKE_TFTP_GET_FD
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


def _web_api_v1(entry):
    query_params = dict(bottle.request.query.decode())
    with ServerAPILink("localhost", "SSAPI") as server:
        api_method = getattr(server, f"web_api_v1_{entry}")
        resp = api_method(query_params)
        code = resp.pop("code")
        if code != 200:
            return bottle.HTTPError(code, resp["message"])
        # transform numpy recarray to make it json-able
        resp[entry] = np_recarray_to_tuple_of_dicts(resp[entry])
        return resp


def _get_logs(ts_from, ts_to, ts_unit, issuers, streams_regexp):
    f = client_sock_file("localhost", WALT_SERVER_TCP_PORT)
    # send message
    TcpRequests.send_id(f, TcpRequests.REQ_DUMP_LOGS)
    params = dict(
        history=(ts_from, ts_to),
        realtime=False,
        issuers=issuers,
        streams_regexp=streams_regexp,
        logline_regexp=None,
        timestamps_format=f"float-{ts_unit}",
        output_format="numpy-pickles",
    )
    pickle.dump(params, f)
    # receive logs
    all_logs = []
    try:
        while True:
            logs = pickle.load(f)
            logs = list(np_recarray_to_tuple_of_dicts(logs))
            all_logs += logs
    except Exception:
        pass
    finally:
        f.close()
    return dict(
            num_logs=len(all_logs),
            logs=all_logs
    )


# this will hold the socket to walt-server-daemon
s_conn = None


def run():
    # instanciate web app
    app = bottle.Bottle()

    @app.route("/")
    @app.route("/index.html")
    def welcome():
        return WELCOME_PAGE

    @app.route("/favicon.ico")
    def favicon():
        bottle.redirect('/doc/_static/logo-walt.png')

    @app.route("/boot/<path:path>")
    def serve_boot(path):
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

    @app.route("/doc")
    def redirect_doc():
        bottle.redirect('/doc/')

    @app.route("/doc/")
    @app.route("/doc/<path:path>")
    def serve_doc(path="index.html"):
        return bottle.static_file(path, root=HTML_DOC_DIR)

    @app.route("/api")
    @app.route("/api/index.html")
    def serve_api_page():
        return API_PAGE

    @app.route("/api/v1/nodes")
    def api_v1_nodes():
        return _web_api_v1("nodes")

    @app.route("/api/v1/images")
    def api_v1_images():
        return _web_api_v1("images")

    @app.route("/api/v1/logs")
    def api_v1_logs():
        query_params = dict(bottle.request.query.decode())
        ts_from = query_params.get("from", None)
        ts_to = query_params.get("to", None)
        ts_unit = query_params.get("ts_unit", "s")
        if ts_from is None or ts_to is None:
            return bottle.HTTPError(400,
                    "Query parameters 'from' and 'to' are required.")
        res = convert_query_param_value(ts_from, float)
        if not res[0]:
            return bottle.HTTPError(400, res[1])
        ts_from = res[1]
        res = convert_query_param_value(ts_to, float)
        if not res[0]:
            return bottle.HTTPError(400, res[1])
        ts_to = res[1]
        if ts_unit == "s":
            pass
        elif ts_unit == "ms":
            ts_from *= 0.001
            ts_to *= 0.001
        else:
            return bottle.HTTPError(400,
                    "Query parameter 'ts_unit' should be 's' (seconds)" +
                    " or 'ms' (milliseconds)")
        now = time()
        for param, ts in (("ts_from", ts_from), ("ts_to", ts_to)):
            if ts < WALT_T0:
                return bottle.HTTPError(400,
                    f"Query parameter '{param}' is invalid " +
                    "(earlier than WALT project startup date!)")
            if ts > now + 2:  # allow time desynchronization up to 2 seconds
                return bottle.HTTPError(400,
                    f"Query parameter '{param}' is invalid, " +
                    "it refers to a date in the future.\n" +
                    "Note: you can use 'ts_unit' query parameter to specify " +
                    "the unit (i.e. 's' for seconds, 'ms' for milliseconds).")
        stream = query_params.get("stream", "")
        streams_regexp = f"^{stream}$" if stream != "" else None
        issuer = query_params.get("issuer", "")
        issuers = (issuer,) if issuer != "" else None
        return _get_logs(ts_from, ts_to, ts_unit, issuers, streams_regexp)

    # run web app
    server = WSGIServer(('', WALT_HTTPD_PORT), app)
    notify_systemd()
    server.serve_forever()
