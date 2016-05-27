#!/usr/bin/env python
import sys, os, time
from termios import tcflush, TCIOFLUSH
from bisect import bisect_right, insort_right
from walt.common.evloop import EventLoop
from walt.common.tools import failsafe_makedirs
from walt.node.const import SERVER_LOGS_FIFO

"""
Read a serial device connected to a sensor mote and
manage logs.
The sensor mote should send a LOGSTART directive after
its startup phase (this allows to discard a potentially
verbose output during the startup phase). Then it should
define a set of logging statements using LOGDEF directives,
and optionaly a set of variables using LOGVAR.
Then, serial log lines matching the LOGDEF directives
will be formatted appropriately and forwarded to the
walt log engine.

Directives format:
LOGSTART
LOGDEF <logstream> <prefix> <separator> <py-format-str>
LOGVAR <var-name> <value>

Example:
[...]
LOGSTART
LOGDEF vizwalt ;T: : {nodeid}:TxStart:{}
LOGDEF vizwalt ;R : {nodeid}:RxStart
LOGVAR nodeid af4e
[...]
;T:aabbccddeeff
[...]
;R
[...]
;T:gghhiijjkkll

This will cause the following walt log entries:

stream   line
------   ----
vizwalt  af4e:TxStart:aabbccddeeff
vizwalt  af4e:RxStart
vizwalt  af4e:TxStart:gghhiijjkkll
"""

class SensorLogsMonitor(object):
    def __init__(self, serial_dev_path):
        self.f = open(serial_dev_path, 'r', 0)
        self.walt_logs = open(SERVER_LOGS_FIFO, 'w')
        # Data does not comes in immediately after we have the
        # device open. Wait a little to make sure we get
        # the data to be flushed.
        time.sleep(0.1)
        self.flush()
        self.logdefs = []
        self.logvars = {}
        log_dir = '/var/log/walt/autolog%s' % serial_dev_path
        failsafe_makedirs(log_dir)
        self.in_dbg_log = open(log_dir + '/in.log', 'w')
        self.out_dbg_log = open(log_dir + '/out.log', 'w')
        self.started = False

    def flush(self):
        tcflush(self.fileno(), TCIOFLUSH)

    # let the event loop know what we are reading on
    def fileno(self):
        return self.f.fileno()

    # when the event loop detects an event for us,
    # read the log line and process it
    def handle_event(self, ts):
        rawline = self.f.readline()
        if rawline == '':  # empty read
            return False # remove from loop => exit
        self.in_dbg_log.write(rawline)
        self.in_dbg_log.flush()
        rawline = rawline.strip()
        words = rawline.split()
        if len(words) == 0:
            return
        first = words[0]
        if not self.started:
            if first == 'LOGSTART':
                self.started = True
        else:
            if first == 'LOGDEF':
                prefix = words[2]
                logdef = (prefix, dict(
                    stream = words[1],
                    sep = words[3],
                    formatting = ' '.join(words[4:])))
                insort_right(self.logdefs, logdef)
            elif first == 'LOGVAR':
                self.logvars[words[1]] = words[2]
            elif len(self.logdefs) > 0:
                # adding a char ('*') ensures that i will point
                # after the matching prefix, even if (rawline == prefix)
                i = bisect_right(self.logdefs, (rawline + '*',))
                if i > 0 and rawline.startswith(self.logdefs[i-1][0]):
                    d = self.logdefs[i-1][1]
                    self.forward_log(ts=ts, rawline=rawline, **d)
    def forward_log(self, ts, rawline, stream, sep, formatting):
        logargs = rawline.split(sep)[1:]
        logline = formatting.format(*logargs, **self.logvars)
        logout = 'TSLOG %(ts)f %(stream)s %(line)s\n' % dict( \
            ts = ts,
            stream = stream,
            line = logline
        )
        print logout.strip()
        self.out_dbg_log.write(logout)
        self.out_dbg_log.flush()
        self.walt_logs.write(logout)
        self.walt_logs.flush()

    def close(self):
        self.walt_logs.close()
        self.f.close()
        self.in_dbg_log.close()
        self.out_dbg_log.close()

def run():
    if len(sys.argv) != 2:
        print 'Usage: %s <serial_dev_path>' % sys.argv[0]
        sys.exit()
    serial_dev_path = sys.argv[1]
    if not os.path.exists(serial_dev_path):
        print 'No such file of directory: %s' % serial_dev_path
        sys.exit()
    sensor_logs_monitor = SensorLogsMonitor(serial_dev_path)
    ev_loop = EventLoop()
    ev_loop.register_listener(sensor_logs_monitor)
    ev_loop.loop()

if __name__ == "__main__":
    run()

