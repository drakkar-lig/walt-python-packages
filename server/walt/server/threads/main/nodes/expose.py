#!/usr/bin/env python
import socket
from walt.common.io import SmartBufferingFileReader, \
                            read_and_copy
from walt.common.tcp import read_pickle, Requests, client_socket

class NodeExposeFeedbackListener:
    def __init__(self, env):
        self.env = env
    # let the event loop know what we are reading on
    def fileno(self):
        return self.env.node_r.fileno()
    # when the event loop detects an event for us, this means
    # the node wrote something on the socket
    # we just have to copy this to the user socket
    def handle_event(self, ts):
        return read_and_copy(
                self.env.node_r, self.env.sock_file)
    def close(self):
        print 'FeedbackListener close()'
        self.env.close()

class NodeExposeSocketListener:
    REQ_ID = Requests.REQ_TCP_TO_NODE
    def __init__(self, ev_loop, sock, sock_file, **kwargs):
        self.ev_loop = ev_loop
        self.node_ip_and_port = None
        self.sock = sock
        self.sock_file = sock_file
        # provide read_available() method on the socket
        self.sock_reader = SmartBufferingFileReader(self.sock_file)
        self.node_r = None
        self.node_w = None
        self.node_s = None
    def get_pair(self, sock):
        sock_r = sock.makefile('r', 0)
        sock_w = sock.makefile('w', 0)
        # provide read_available() method
        sock_r = SmartBufferingFileReader(sock_r)
        return sock_r, sock_w
    def open_channel_to_node(self):
        s = client_socket(*self.node_ip_and_port)
        r, w = self.get_pair(s)
        return s, r, w
    def start(self):
        try:
            self.node_s, self.node_r, self.node_w = self.open_channel_to_node()
        except:
            self.sock_file.write('Could not connect to %s:%d!\n' % \
                                    self.node_ip_and_port)
            return False    # we should close
        # create a new listener on the event loop for reading
        # what the node outputs
        feedback_listener = NodeExposeFeedbackListener(self)
        self.ev_loop.register_listener(feedback_listener)
        self.sock_file.write('OK\n')
    # let the event loop know what we are reading on
    def fileno(self):
        if self.sock_file.closed:
            return None
        return self.sock_file.fileno()
    # handle_event() will be called when the event loop detects
    # new input data for us.
    def handle_event(self, ts):
        if self.node_ip_and_port == None:
            # we did not get the parameters yet, let's do it
            params = read_pickle(self.sock_file)
            if params == None:
                self.close()    # issue
                return False
            self.node_ip_and_port = (params['node_ip'], params['node_port'])
            # we now have all info to connect to the node
            return self.start()
        else:
            # otherwise we are all set. Thus, getting input data means
            # data was sent on the other end.
            return read_and_copy(
                self.sock_reader, self.node_w)
    def close(self):
        print 'ExposeSocketListener close()'
        if self.sock:
            # let the client know we are closing all
            #self.sock.shutdown(socket.SHUT_RDWR)
            self.sock_file.close()
            self.sock.close()
            self.sock = None
        if self.node_s:
            # let the node know we are closing all
            #self.node_s.shutdown(socket.SHUT_RDWR)
            self.node_r.close()
            self.node_w.close()
            self.node_s.close()
            self.node_s = None

class ExposeManager(object):
    def __init__(self, tcp_server, ev_loop):
        for cls in [ NodeExposeSocketListener ]:
            tcp_server.register_listener_class(
                    req_id = cls.REQ_ID,
                    cls = cls,
                    ev_loop = ev_loop)

