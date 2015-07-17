#!/usr/bin/env python

import datetime, sys, os, signal, socket
from subprocess import Popen, PIPE
from plumbum import cli
from walt.common.logs import LogsConnectionToServer
from walt.common.evloop import EventLoop
from walt.node.tools import lookup_server_ip

STDOUT = 1
STDERR = 2
STREAM_NAMES = { STDOUT: 'stdout', STDERR: 'stderr' }
STD_STREAMS = { STDOUT: sys.stdout, STDERR: sys.stderr }

class LogListener(object):
    def __init__(self, f, cmdline, pid, stream, server_ip):
        self.f = f
        self.conn = LogsConnectionToServer(server_ip)
        prog_name = os.path.basename(cmdline[0])
        self.conn.start_new_incoming_logstream(
                prog_name + '.' + str(pid) + '.' +
                STREAM_NAMES[stream])
        self.stdstream = STD_STREAMS[stream]
    def handle_event(self, ts):
        line = self.f.readline()
        if line == '':  # empty read
            return False # remove from loop
        self.stdstream.write(line)
        self.stdstream.flush()
        self.conn.log(line=line.strip(), timestamp=datetime.datetime.now())
    def fileno(self):
        return self.f.fileno()
    def close(self):
        self.f.close()

class WalTMonitor(cli.Application):
    """Run and monitor <cmdline>, sending logs to the WalT server"""
    server_ip = cli.SwitchAttr("--server-ip", str, default = None,
            help = "Specify the server ip (useful for debugging).")

    def main(self, *cmdline):
        if len(cmdline) == 0:
            WalTMonitor.help(self)
            return
        if self.server_ip == None:
            self.server_ip = lookup_server_ip()
        # python ignores SIGPIPE by default.
        # this could cause issues if the command that will
        # be popen-ed uses pipes (such as a shell script).
        # so we restore it.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        ev_loop = EventLoop()
        process = Popen(cmdline, stdout=PIPE, stderr=PIPE)
        out_listener = LogListener( process.stdout, cmdline,
                                    process.pid, STDOUT,
                                    self.server_ip)
        err_listener = LogListener( process.stderr, cmdline,
                                    process.pid, STDERR,
                                    self.server_ip)
        ev_loop.register_listener(err_listener)
        ev_loop.register_listener(out_listener)
        try:
            ev_loop.loop()
        except KeyboardInterrupt:
            print
            print 'Interrupted.'
        except socket.error:
            print 'Socket error.'

def run():
    WalTMonitor.run()

if __name__ == "__main__":
    run()

