from time import time
from walt.node.tools import lookup_server_ip
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import write_pickle, client_socket, \
                            Requests
from walt.common.tools import remove_non_utf8

class LogsFlowToServer(object):
    server_ip = lookup_server_ip()
    def __init__(self, stream_name):
        s = client_socket(LogsFlowToServer.server_ip, WALT_SERVER_TCP_PORT)
        self.stream = s.makefile()
        Requests.send_id(self.stream, Requests.REQ_NEW_INCOMING_LOGS)
        self.stream.write('%s\n' % stream_name)
        self.stream.flush()
        self.last_used = time()
    def log(self, line, timestamp = None):
        if timestamp == None:
            timestamp = time()
        self.stream.write('%.6f %s\n' % (timestamp, remove_non_utf8(line)))
        self.stream.flush()
        self.last_used = time()
    def close(self):
        self.stream.close()
