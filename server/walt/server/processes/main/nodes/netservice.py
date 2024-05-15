from collections import defaultdict

from walt.server.tools import NonBlockingSocket
from walt.server.const import WALT_NODE_NET_SERVICE_PORT

NODE_REQUEST_DELAY_SECS = 15.0


class ServerToNodeRequest(NonBlockingSocket):
    def __init__(self, ev_loop, node, req, cb, env):
        self.node = node
        self.req = req
        self.cb = cb
        self.env = env
        NonBlockingSocket.__init__(self, ev_loop,
                    self.node.ip, WALT_NODE_NET_SERVICE_PORT,
                    NODE_REQUEST_DELAY_SECS)

    def run(self):
        self.start_connect()

    def on_connect_timeout(self):
        self.cb(self.env, self.node, "Connection timed out")

    def on_connect(self):
        try:
            self.send(f"MODE single\n{self.req}\n".encode("ascii"))
        except (ConnectionRefusedError, OSError) as e:
            if isinstance(e, ConnectionRefusedError):
                result_msg = "Connection refused"
            else:
                result_msg = e.strerror
            print(result_msg)
            self.cb(self.env, self.node, result_msg)
            # ev_loop will call close()
            return False
        self.start_wait_read()  # wait for the response

    def on_read_timeout(self):
        self.cb(self.env, self.node, "Timed out waiting for reply")

    def on_read_ready(self):
        resp = b''
        while True:
            try:
                c = self.recv(1)
            except Exception as e:
                print(e)
                result_msg = "Broken connection"
                self.cb(self.env, self.node, result_msg)
                # ev_loop will call close()
                return False
            if c == b'\n':
                break
            elif c == b'':
                break
            resp += c
        resp = tuple(part.strip() for part in
                     resp.decode('ascii').split(" ", 1))
        if resp[0] == "OK":
            self.cb(self.env, self.node, "OK")
        elif len(resp) == 2:
            self.cb(self.env, self.node, resp[1])
        else:
            self.cb(self.env, self.node, "Node did not respond properly")
        return False  # ev_loop will call close()


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
