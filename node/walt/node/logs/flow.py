import subprocess
from time import time
from walt.common.tools import remove_non_utf8

WALT_LOG_CAT_BINARY = subprocess.check_output('which walt-log-cat',
                            shell = True).strip()

class LogsFlowToServer(object):
    def __init__(self, stream_name):
        self.popen = subprocess.Popen([WALT_LOG_CAT_BINARY, '--ts', stream_name],
                        stdin=subprocess.PIPE)
        self.stream = self.popen.stdin
        self.last_used = time()
    def log(self, line, timestamp = None):
        if timestamp == None:
            timestamp = time()
        self.stream.write('%.6f %s\n' % (timestamp, remove_non_utf8(line)))
        self.stream.flush()
        self.last_used = time()
    def close(self):
        self.stream.close()
