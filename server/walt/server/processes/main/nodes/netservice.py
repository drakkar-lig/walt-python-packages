import errno
import socket
from collections import defaultdict
from time import time

from walt.common.evloop import POLL_OPS_READ, POLL_OPS_WRITE
from walt.server.const import WALT_NODE_NET_SERVICE_PORT

NODE_REQUEST_DELAY_SECS = 15.0


class REQUEST_STATUS:
    INIT = 0
    CONNECTING = 1
    WAITING_RESPONSE = 2
    DONE = 3


def non_blocking_connect(sock, ip, port):
    try:
        sock.connect((ip, port))
    except BlockingIOError as e:
        if e.errno == errno.EINPROGRESS:
            pass  # ok, ignore
        else:
            raise  # unexpected, raise


class ServerToNodeRequest:
    def __init__(self, ev_loop, node, req, cb, env):
        self.ev_loop = ev_loop
        self.node = node
        self.req = req
        self.cb = cb
        self.env = env
        self.sock = None
        self.status = REQUEST_STATUS.INIT

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # connect call should not block, thus we use non-blocking mode
        # and let the event loop recall us when we can *write* on the socket
        self.sock.setblocking(False)  # connect call should not block
        non_blocking_connect(self.sock, self.node.ip, WALT_NODE_NET_SERVICE_PORT)
        self.status = REQUEST_STATUS.CONNECTING
        self.ev_loop.register_listener(self, POLL_OPS_WRITE)
        # we also set a timeout on the event loop
        timeout_at = time() + NODE_REQUEST_DELAY_SECS
        self.ev_loop.plan_event(ts=timeout_at, callback=self.on_timeout)

    def on_timeout(self):
        if self.status != REQUEST_STATUS.DONE:
            self.ev_loop.remove_listener(self)
            self.close()
            if self.status == REQUEST_STATUS.CONNECTING:
                result_msg = "Connection timed out"
            else:
                result_msg = "Timed out waiting for reply"
            self.cb(self.env, self.node, result_msg)
            self.status = REQUEST_STATUS.DONE

    def handle_event(self, ts):
        # the event loop detected an event for us
        if self.status == REQUEST_STATUS.CONNECTING:
            self.sock.setblocking(True)
            try:
                self.sock.send(self.req.encode("ascii") + b"\n")
            except (ConnectionRefusedError, OSError) as e:
                if isinstance(e, ConnectionRefusedError):
                    result_msg = "Connection refused"
                else:
                    result_msg = e.strerror
                print(result_msg)
                self.cb(self.env, self.node, result_msg)
                return False  # ev_loop should remove this listener
            self.status = REQUEST_STATUS.WAITING_RESPONSE
            self.ev_loop.update_listener(self, POLL_OPS_READ)
        elif self.status == REQUEST_STATUS.WAITING_RESPONSE:
            rfile = self.sock.makefile()
            resp = rfile.readline().split(" ", 1)
            rfile.close()
            resp = tuple(part.strip() for part in resp)
            if resp[0] == "OK":
                self.cb(self.env, self.node, "OK")
            elif len(resp) == 2:
                self.cb(self.env, self.node, resp[1])
            return False  # ev_loop should remove this listener

    # let the event loop know what we are reading on
    def fileno(self):
        return self.sock.fileno()

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        self.status = REQUEST_STATUS.DONE


def node_request_cb(env, node, result_msg):
    env["results"][result_msg].append(node)
    env["num_nodes"] -= 1
    if env["num_nodes"] == 0:  # done
        cb, cb_kwargs, results = env["cb"], env["cb_kwargs"], env["results"]
        cb(results, **cb_kwargs)


def node_request(ev_loop, nodes, req, cb, cb_kwargs):
    num_nodes = len(nodes)
    results = defaultdict(list)
    if num_nodes == 0:
        cb(results, **cb_kwargs)
        return
    env = dict(num_nodes=num_nodes, results=results, cb=cb, cb_kwargs=cb_kwargs)
    for node in nodes:
        request = ServerToNodeRequest(ev_loop, node, req, node_request_cb, env)
        request.run()
