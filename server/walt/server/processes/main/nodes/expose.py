#!/usr/bin/env python
from walt.common.io import read_and_copy
from walt.common.tcp import Requests, client_sock_file, read_pickle


class NodeExposeFeedbackListener:
    def __init__(self, env):
        self.env = env

    # let the event loop know what we are reading on
    def fileno(self):
        return self.env.node_sock_file.fileno()

    def handle_event(self, ts):
        if self.env.ready:
            # when the event loop detects an event for us, this means
            # the node wrote something on the socket
            # we just have to copy this to the user socket
            return read_and_copy(self.env.node_sock_file, self.env.client_sock_file)
        else:
            return False

    def close(self):
        self.env.close()


class NodeExposeSocketListener:
    REQ_ID = Requests.REQ_TCP_TO_NODE

    def __init__(self, ev_loop, sock_file, **kwargs):
        self.ev_loop = ev_loop
        self.node_ip_and_port = None
        self.client_sock_file = sock_file
        self._fileno = sock_file.fileno()
        self.node_sock_file = None

    def open_channel_to_node(self):
        return client_sock_file(*self.node_ip_and_port)

    @property
    def ready(self):
        return (self.node_sock_file is not None and
                self.client_sock_file is not None)

    def start(self):
        try:
            self.node_sock_file = self.open_channel_to_node()
        except Exception:
            self.client_sock_file.write(
                ("Could not connect to %s:%d!\n" % self.node_ip_and_port).encode(
                    "utf-8"
                )
            )
            return False  # we should close
        # create a new listener on the event loop for reading
        # what the node outputs
        feedback_listener = NodeExposeFeedbackListener(self)
        self.ev_loop.register_listener(feedback_listener)
        self.client_sock_file.write(b"OK\n")

    # let the event loop know what we are reading on
    def fileno(self):
        return self._fileno

    # handle_event() will be called when the event loop detects
    # new input data for us.
    def handle_event(self, ts):
        if self.node_ip_and_port is None:
            # we did not get the parameters yet, let's do it
            params = read_pickle(self.client_sock_file)
            if params is None:
                self.close()  # issue
                return False
            self.node_ip_and_port = (params["node_ip"], params["node_port"])
            # we now have all info to connect to the node
            return self.start()
        elif not self.ready:
            return False    # we should not get events!
        else:
            # otherwise we are all set. Thus, getting input data means
            # data was sent on the other end.
            return read_and_copy(self.client_sock_file, self.node_sock_file)

    def close(self):
        if self.client_sock_file:
            self.client_sock_file.close()
            self.client_sock_file = None
        if self.node_sock_file:
            self.node_sock_file.close()
            self.node_sock_file = None


class ExposeManager(object):
    def __init__(self, tcp_server, ev_loop):
        for cls in [NodeExposeSocketListener]:
            tcp_server.register_listener_class(
                req_id=cls.REQ_ID, cls=cls, ev_loop=ev_loop
            )
