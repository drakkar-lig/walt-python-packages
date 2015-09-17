from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import read_pickle, write_pickle, client_socket, \
                            Requests

class LogsConnectionToServer(object):
    def __init__(self, walt_server_host):
        s = client_socket(walt_server_host, WALT_SERVER_TCP_PORT)
        self.stream = s.makefile()
    def read_log_record(self):
        return read_pickle(self.stream)
    def request_log_dump(self):
        Requests.send_id(self.stream, Requests.REQ_DUMP_LOGS)
    def start_new_incoming_logstream(self, stream_name):
        Requests.send_id(self.stream, Requests.REQ_NEW_INCOMING_LOGS)
        write_pickle(stream_name, self.stream)
    def log(self, **kwargs):
        write_pickle(kwargs, self.stream)
    def close(self):
        self.stream.close()

