import socket, cPickle as pickle
from walt.common.constants import WALT_SERVER_LOGS_PORT

REQ_NEW_INCOMING_LOGS = 0
REQ_DUMP_LOGS = 1

def read_encoded_from_log_stream(stream):
    return pickle.load(stream)

def write_encoded_to_log_stream(obj, stream):
    pickle.dump(obj, stream, pickle.HIGHEST_PROTOCOL)
    stream.flush()

class LogsConnectionToServer(object):
    def __init__(self, walt_server_host):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((walt_server_host, WALT_SERVER_LOGS_PORT))
        self.stream = s.makefile()
    def read_log_record(self):
        try:
            return read_encoded_from_log_stream(self.stream)
        except Exception:
            return None
    def request_log_dump(self):
        write_encoded_to_log_stream(
                (REQ_DUMP_LOGS,None), self.stream)
    def start_new_incoming_logstream(self, stream_name):
        write_encoded_to_log_stream(
                (REQ_NEW_INCOMING_LOGS,stream_name), self.stream)
    def log(self, **kwargs):
        write_encoded_to_log_stream(kwargs, self.stream)

