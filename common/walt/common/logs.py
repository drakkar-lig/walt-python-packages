from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import read_pickle, write_pickle, client_socket, \
                            REQ_NEW_INCOMING_LOGS, REQ_DUMP_LOGS

class LogsConnectionToServer(object):
    def __init__(self, walt_server_host):
        s = client_socket(walt_server_host, WALT_SERVER_TCP_PORT)
        self.stream = s.makefile()
    def read_log_record(self):
        return read_pickle(self.stream)
    def request_log_dump(self):
        write_pickle(REQ_DUMP_LOGS, self.stream)
    def start_new_incoming_logstream(self, stream_name):
        write_pickle(REQ_NEW_INCOMING_LOGS, self.stream)
        write_pickle(stream_name, self.stream)
    def log(self, **kwargs):
        write_pickle(kwargs, self.stream)

