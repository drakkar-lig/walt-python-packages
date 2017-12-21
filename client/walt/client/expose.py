#!/usr/bin/env python
from walt.client.config import conf
from select import select
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.io import SmartBufferingFileReader, read_and_copy
from walt.common.tcp import Requests, write_pickle, client_socket, server_socket

class TCPExposer:
    def __init__(self, local_port, node_ip, node_port):
        self.local_port = local_port
        self.params = dict(
            node_ip = node_ip,
            node_port = node_port
        )
        self.associations = {}
    def run(self):
        self.local_server_s = server_socket(self.local_port)
        while True:
            read_socks = self.associations.keys() + [ self.local_server_s ]
            select_args = [ read_socks, [], read_socks ]
            rlist, wlist, elist = select(*select_args)
            if len(elist) > 0 or len(rlist) == 0:
                break
            sock_r = rlist[0]
            if sock_r == self.local_server_s:
                if self.event_on_server_s() == False:
                    break
            else:
                sock_w, other_sock_r, other_sock_w = self.associations[sock_r]
                if read_and_copy(sock_r, other_sock_w) == False:
                    for s in (sock_r, sock_w, other_sock_r, other_sock_w):
                        s.close()
                    del self.associations[sock_r]
                    del self.associations[other_sock_r]
    def get_pair(self, sock):
        sock_r = sock.makefile('r', 0)
        sock_w = sock.makefile('w', 0)
        # provide read_available() method
        sock_r = SmartBufferingFileReader(sock_r)
        return sock_r, sock_w
    def open_channel_to_node(self):
        # connect
        server_host = conf['server']
        s = client_socket(server_host, WALT_SERVER_TCP_PORT)
        sock_r, sock_w = self.get_pair(s)
        # write request id
        Requests.send_id(sock_w, Requests.REQ_TCP_TO_NODE)
        # send parameters
        write_pickle(self.params, sock_w)
        # wait for the status message from the server
        status = sock_r.readline().strip()
        if status == 'OK':
            print 'New connection forwarded to node.'
            return sock_r, sock_w
        else:
            sock_r.close()
            sock_w.close()
            s.close()
            print status
            return None, None
    def event_on_server_s(self):
        conn_s, addr = self.local_server_s.accept()
        chan_sock_r, chan_sock_w = self.open_channel_to_node()
        if chan_sock_r == None:
            conn_s.close()
            return
        conn_sock_r, conn_sock_w = self.get_pair(conn_s)
        self.associations[conn_sock_r] = conn_sock_w, chan_sock_r, chan_sock_w
        self.associations[chan_sock_r] = chan_sock_w, conn_sock_r, conn_sock_w
    def close(self):
        for s1, t in self.associations.items():
            if not s1.closed:
                s2, s3, s4 = t
                for s in (s1, s2, s3, s4):
                    s.close()
        self.local_server_s.close()
