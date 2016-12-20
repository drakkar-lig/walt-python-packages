from time import time
from walt.node.tools import lookup_server_ip
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import write_pickle, client_socket, \
                            Requests

def remove_non_utf8(s):
    return s.decode('utf-8','ignore').encode("utf-8")

class LogsFlowToServer(object):
    server_ip = lookup_server_ip()
    def __init__(self, stream_name):
        s = client_socket(LogsFlowToServer.server_ip, WALT_SERVER_TCP_PORT)
        self.stream = s.makefile()
        Requests.send_id(self.stream, Requests.REQ_NEW_INCOMING_LOGS)
        write_pickle(stream_name, self.stream)
        self.last_used = time()
    def log(self, line, timestamp = None):
        if timestamp == None:
            timestamp = time()
        write_pickle(dict(
                line = remove_non_utf8(line),
                timestamp = timestamp
            ), self.stream)
        self.last_used = time()
    def close(self):
        self.stream.close()
