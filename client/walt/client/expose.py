#!/usr/bin/env python
from walt.client.config import conf
from select import select
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.io import read_and_copy
from walt.common.tcp import Requests, write_pickle, client_sock_file, \
                            server_socket, SmartSocketFile

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
                paired_sock = self.associations[sock_r]
                if read_and_copy(sock_r, paired_sock) == False:
                    for s in (sock_r, paired_sock):
                        s.close()
                    del self.associations[sock_r]
                    del self.associations[paired_sock]
    def open_channel_to_node(self):
        # connect
        server_host = conf['server']
        sock_file = client_sock_file(server_host, WALT_SERVER_TCP_PORT)
        # write request id
        Requests.send_id(sock_file, Requests.REQ_TCP_TO_NODE)
        # send parameters
        write_pickle(self.params, sock_file)
        # wait for the status message from the server
        status = sock_file.readline().strip()
        if status == 'OK':
            print 'New connection forwarded to node.'
            return sock_file
        else:
            sock_file.close()
            print status
            return None
    def event_on_server_s(self):
        conn_s, addr = self.local_server_s.accept()
        node_channel = self.open_channel_to_node()
        if node_channel == None:
            conn_s.close()
            return
        client_channel = SmartSocketFile(conn_s)
        self.associations[client_channel] = node_channel
        self.associations[node_channel] = client_channel
    def close(self):
        for f1, f2 in self.associations.items():
            f1.close()
            f2.close()
        self.local_server_s.close()
