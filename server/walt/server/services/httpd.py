import bottle
import json
import os
import sdnotify
import shlex
import socket
import walt

from functools import lru_cache
from gevent.fileobject import FileObject
from gevent.lock import RLock as Lock
from gevent.pywsgi import WSGIServer
from gevent import subprocess
from pathlib import Path
from time import time
from walt.common.apilink import ServerAPILink
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import Requests as TcpRequests
from walt.common.tcp import MyPickle as pickle, client_sock_file
from walt.common.unix import Requests as UnixRequests
from walt.common.unix import bind_to_random_sockname, recv_msg_fds
from walt.server.const import UNIX_SERVER_SOCK_PATH
from walt.server.tools import np_recarray_to_tuple_of_dicts, convert_query_param_value
from walt.server.tools import ttl_cache, get_server_ip
from importlib.resources import files

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
HTML_DOC_DIR = str(files(walt) / "doc" / "html")

WALT_T0 = 1340000000  # Epoch timestamp corresponding to some time in june 2012
HTTP_BOOT_SERVER_PRIV_KEY = Path("/var/lib/walt/http-boot/private.pem")
HTTP_BOOT_SERVER_PUB_KEY = Path("/var/lib/walt/http-boot/public.pem")


# this will hold the socket to walt-server-daemon
s_conn = None
# this will allow to serialize communication with the server on
# the unix socket
s_lock = Lock()


def open_from_server_daemon(path, node_ip):
    req_id = UnixRequests.REQ_FAKE_TFTP_GET_FD
    args = ()
    kwargs = dict(node_ip=node_ip, path=path)
    fds = query_main_daemon(req_id, args, kwargs, maxfds=1)
    if isinstance(fds, Exception):
        raise fds
    assert len(fds) == 1
    fd = fds[0]
    return fd


def query_main_daemon(req_id, args, kwargs, msglen=256, maxfds=0):
    with s_lock:
        return _query_main_daemon(req_id, args, kwargs, msglen, maxfds)


def _query_main_daemon(req_id, args, kwargs, msglen, maxfds):
    global s_conn
    req = req_id, args, kwargs
    error = "Unknown error, sorry."
    for i in range(2):
        if s_conn is None:
            s_conn = get_socket()
        try:
            # send message
            s_conn.send(pickle.dumps(req))
            # receive the response
            if maxfds > 0:
                msg, fds = recv_msg_fds(s_conn, msglen, maxfds)
            else:
                msg = s_conn.recv(msglen)
            resp = pickle.loads(msg)
            # return result
            assert "status" in resp
            if resp["status"] == "OK":
                if maxfds > 0:
                    return fds
                elif "response_text" in resp:
                    return resp["response_text"]
                else:
                    return "OK\n"
            else:
                assert "error_msg" in resp
                error = resp["error_msg"]
                continue
        except OSError as e:
            if i == 0:
                # try to re-init the socket to walt-server-daemon
                s_conn.close()
                s_conn = None
                continue
            else:
                return bottle.HTTPError(500, str(e))
    if error == "NO SUCH FILE":
        return bottle.HTTPError(404, "No such file.")
    else:
        return bottle.HTTPError(400, error)


def requester_ip():
    requester_ip = bottle.request.environ.get("REMOTE_ADDR")
    requester_ip = requester_ip.lstrip("::ffff:")
    # For running tests (i.e. make test) the client can add
    # a parameter called "fake_requester_ip".
    # However, for security reason, this is only allowed
    # when the real client IP is the server IP.
    server_ip = get_server_ip()
    if requester_ip == server_ip:
        fake_requester_ip = bottle.request.query.get("fake_requester_ip")
        if fake_requester_ip is not None:
            return fake_requester_ip
    return requester_ip


def vpn_enroll(node_ip, pubkey_file):
    pubkey = pubkey_file.read()
    kwargs = dict(node_ip=node_ip, pubkey=pubkey)
    return query_main_daemon(UnixRequests.REQ_VPN_ENROLL, (), kwargs)


def dump_generated_file(file_id, **kwargs):
    req_id = UnixRequests.REQ_GENERATE_FILE
    kwargs.update(file_id=file_id)
    return query_main_daemon(req_id, (), kwargs, msglen=65536)


def get_property_value(property_id, **kwargs):
    req_id = UnixRequests.REQ_PROPERTY
    kwargs.update(property_id=property_id)
    return query_main_daemon(req_id, (), kwargs)


@ttl_cache(5)
def dump_ssh_entrypoint_host_keys():
    return dump_generated_file("ssh-ep-host-keys")


def dump_ssh_pubkey_cert():
    return dump_generated_file("ssh-pubkey-cert",
                               node_ip=requester_ip())


def notify_systemd():
    if "NOTIFY_SOCKET" in os.environ:
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


_cache_context = {}


@lru_cache
def _generate_boot_sig(key):
    # notes:
    # * we had to pass fd using a _cache_context global
    #   variable and not as a parameter because it should
    #   not be taken into account by lru_cache for cache
    #   lookup.
    # * for coherency between cache and non-cache paths
    #   it is important not to close fd here (thus the
    #   parameter closefd=False)
    fd = _cache_context["fd"]
    boot_img = FileObject(fd, mode="rb", closefd=False)
    boot_img_content = boot_img.read()
    boot_img.close()
    cmd = f"openssl dgst -sha256 -hex"
    res = subprocess.run(shlex.split(cmd),
                         input=boot_img_content,
                         capture_output=True)
    sha256 = res.stdout.decode().split()[1]
    cmd = f"openssl dgst -sign {HTTP_BOOT_SERVER_PRIV_KEY} -sha256 -hex"
    res = subprocess.run(shlex.split(cmd),
                         input=boot_img_content,
                         capture_output=True)
    rsa2048 = res.stdout.decode().split()[1]
    ts = int(time())
    return f"{sha256}\nts: {ts}\nrsa2048: {rsa2048}\n"


def get_boot_sig(fd):
    stat =  os.fstat(fd)
    key = (stat.st_ino, stat.st_mtime, stat.st_size)
    _cache_context.update(fd=fd)
    return _generate_boot_sig(key)


def generate_boot_server_keys():
    if not HTTP_BOOT_SERVER_PRIV_KEY.exists():
        HTTP_BOOT_SERVER_PRIV_KEY.parent.mkdir(parents=True, exist_ok=True)
        cmd = f"openssl genrsa -out {HTTP_BOOT_SERVER_PRIV_KEY} 2048"
        subprocess.run(shlex.split(cmd), check=True)
    if not HTTP_BOOT_SERVER_PUB_KEY.exists():
        HTTP_BOOT_SERVER_PUB_KEY.parent.mkdir(parents=True, exist_ok=True)
        cmd = (f"openssl rsa -in {HTTP_BOOT_SERVER_PRIV_KEY} "
               f"-out {HTTP_BOOT_SERVER_PUB_KEY} -pubout -outform PEM")
        subprocess.run(shlex.split(cmd), check=True)


class MyBottle(bottle.Bottle):
    def default_error_handler(self, error):
        prefer_header = bottle.request.get_header("Prefer")
        if prefer_header is not None:
            if prefer_header.startswith("errors="):
                error_format = prefer_header[7:]
                if error_format == "text-only":
                    bottle.response.content_type = "text/plain"
                    return error.body + "\n"
                if error_format == "json":
                    bottle.response.content_type = 'application/json'
                    return json.dumps(dict(error = error.body,
                                           status_code = error.status_code))
        return super().default_error_handler(error)


def run():
    # generate rsa boot server keys if not done yet
    generate_boot_server_keys()

    # instanciate web app
    app = MyBottle()

    @app.route("/")
    @app.route("/index.html")
    def welcome():
        return WELCOME_PAGE

    @app.route("/favicon.ico")
    def favicon():
        bottle.redirect('/doc/_static/logo-walt.png')

    @app.route("/boot/<path:path>")
    def serve_boot(path):
        # for a virtual node actually running on the server,
        # the IP address of the socket peer does not match
        # the node IP. For this case, URL may indicate the
        # node_ip as an URL parameter.
        node_ip = bottle.request.query.get("node_ip")
        if node_ip is None:
            node_ip = requester_ip()
        fd = open_from_server_daemon(node_ip=node_ip, path="/"+path)
        bottle.response.add_header("Content-Length", os.fstat(fd).st_size)
        return FileObject(fd, mode="rb")

    @app.route("/walt-vpn/per-ip/<path:path>")
    def serve_vpn_per_mac(path):
        ip_dash, path = path.split('/', maxsplit=1)
        ip = ip_dash.replace('-', '.')
        if path == "boot.sig":
            # this file is generated from boot.img on the fly
            # because it includes a signature using the VPN private key
            fd = open_from_server_daemon(node_ip=ip, path="/boot.img")
            content = get_boot_sig(fd)
            os.close(fd)
            return content
        else:
            fd = open_from_server_daemon(node_ip=ip, path="/"+path)
            bottle.response.add_header("Content-Length", os.fstat(fd).st_size)
            return FileObject(fd, mode="rb")

    @app.route("/walt-vpn/enroll", method='POST')
    def serve_vpn_enroll():
        node_ip = requester_ip()
        pubkey = bottle.request.files.get('ssh-pubkey')
        if pubkey is None:
            return bottle.HTTPError(400, "Public key not provided.")
        return vpn_enroll(node_ip, pubkey.file)

    @app.route("/walt-vpn/node-conf/ssh-pubkey-cert")
    def serve_ssh_pubkey_cert():
        return dump_ssh_pubkey_cert()

    @app.route("/walt-vpn/node-conf/ssh-entrypoint-host-keys")
    def serve_ssh_entrypoint_host_keys():
        return dump_ssh_entrypoint_host_keys()

    @app.route("/walt-vpn/node-conf/http-path")
    def serve_vpn_http_path():
        node_ip = requester_ip()
        node_ip_dash = node_ip.replace('.', '-')
        return f"walt-vpn/per-ip/{node_ip_dash}"

    @app.route("/walt-vpn/node-conf/vpn-mac")
    def serve_vpn_mac():
        return get_property_value("node.vpn.mac", node_ip=requester_ip())

    @app.route("/walt-vpn/node-conf/ssh-entrypoint")
    def serve_ssh_entrypoint():
        return get_property_value("server.vpn.ssh-entrypoint")

    @app.route("/walt-vpn/node-conf/http-entrypoint")
    def serve_http_entrypoint():
        return get_property_value("server.vpn.http-entrypoint")

    @app.route("/walt-vpn/node-conf/boot-mode")
    def serve_vpn_boot_mode():
        return get_property_value("server.vpn.boot-mode")

    @app.route("/walt-vpn/node-conf/public.pem")
    def serve_http_boot_public_pem():
        return bottle.static_file(HTTP_BOOT_SERVER_PUB_KEY.name,
                                  str(HTTP_BOOT_SERVER_PUB_KEY.parent))

    # This route can be used to manually check that an HTTP VPN endpoint
    # properly redirects "/walt-vpn/<something>" URLs here.
    # "walt-server-setup --edit-conf" also uses the same URL to validate
    # user entries, but in this case walt-server-httpd is not running.
    # So walt-server-setup implements a mini and temporary web server
    # which also handles this route.
    @app.route("/walt-vpn/server")
    def serve_vpn_server():
        return socket.getfqdn() + "\n"

    @app.route("/doc")
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
