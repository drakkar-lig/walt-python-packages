import re
import sys

from plumbum import cli


class TeeStream:
    def __init__(self, std_stream, log_file, log_prefix):
        self.start_of_line = True
        self.streams = (std_stream,)
        if log_file is not None:
            self.streams += (open(log_file, "w"),)
        self.log_prefix = log_prefix

    def write_all(self, buf):
        for i, stream in enumerate(self.streams):
            stream.write(buf)
            if i > 0:
                stream.flush()

    def write(self, buf):
        if self.log_prefix is None:
            self.write_all(buf)
        else:
            for chunk in re.split("([\r\n])", buf):
                if len(chunk) > 0:
                    if self.start_of_line:
                        self.write_all("[" + self.log_prefix + "] ")
                        self.start_of_line = False
                    self.write_all(chunk)
                    if chunk in "\r\n":
                        self.start_of_line = True

    def flush(self):
        return self.streams[0].flush()

    def fileno(self):
        return self.streams[0].fileno()


class LoggedApplication(cli.Application):
    _log_file = None
    _log_prefix = None

    def init_logs(self):
        if self._log_file is not None or self._log_prefix is not None:
            sys.stdout = TeeStream(sys.stdout, self._log_file, self._log_prefix)
            sys.stderr = TeeStream(sys.stderr, self._log_file, self._log_prefix)

    @cli.switch("--log-file", str)
    def set_log_file(self, log_file):
        """specify log filename for stdin / stderr"""
        self._log_file = log_file

    @cli.switch("--log-prefix", str)
    def set_log_prefix(self, log_prefix):
        """specify prefix to identify logs"""
        self._log_prefix = log_prefix
