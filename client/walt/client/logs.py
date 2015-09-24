import sys
from plumbum import cli
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import read_pickle, write_pickle, client_socket, \
                            Requests
from walt.client.config import conf
from walt.client.link import ClientToServerLink
from walt.client.tools import confirm

DEFAULT_FORMAT_STRING= \
   '{timestamp:%H:%M:%S.%f} {sender}.{stream} -> {line}'

WALT_LOG_SHOW_HELP = {
    'format': """\
Option --format allows to specify the python string formating
that will be used to print the log records.
""",
    'history': """\
All logs are saved in a database on the walt server. You may retrieve 
them by using option --history <range>.

The <range> may be either 'full', 'none', or have the form
'[<start>]:[<end>]'.
Omitting <start> means the range has no limit in the past.
Omitting <end> means logs up to now should match.
Thus the range ':' is equivalent to using the keyword 'full'.
 
If specified, <start> and <end> boundaries must be a relative offset
to the current time, in the form '-<num><unit>', such as '-40s', '-5m',
'-1h', '-10d' (resp. seconds, minutes, hours and days).
""",
    'realtime': """\
Pseudo-realtime mode may be enabled or disabled by using option --realtime.
In this mode, 'walt log show' will wait for incoming log records and
display them.

Note that you may combine --realtime and --history, e.g.:
$ walt log show --history -2min: --realtime
This will display the logs from 2 minutes in the past to now and then
continue listening for new incoming logs.
"""
}

SECONDS_PER_UNIT = {'s':1, 'm':60, 'h':3600, 'd':86400}
NUM_LOGS_CONFIRM_TRESHOLD = 1000

class LogsFlowFromServer(object):
    def __init__(self, walt_server_host):
        s = client_socket(walt_server_host, WALT_SERVER_TCP_PORT)
        self.f_read = s.makefile('r', 0)
        self.f_write = s.makefile('w', 0)
    def read_log_record(self):
        return read_pickle(self.f_read)
    def request_log_dump(self, **kwargs):
        Requests.send_id(self.f_write, Requests.REQ_DUMP_LOGS)
        write_pickle(kwargs, self.f_write)
    def close(self):
        self.f_read.close()
        self.f_write.close()

class WaltLogShowImpl(cli.Application):
    """Dump logs on standard output"""
    help_messages = []

    format_string = cli.SwitchAttr(
                "--format",
                str,
                argname = 'LOG_FORMAT',
                default = DEFAULT_FORMAT_STRING,
                help= """format used to print logs (see --help-about format)""")
    realtime = cli.Flag(
                "--realtime",
                default = False,
                help= """enable realtime mode (see --help-about realtime)""")
    history_range = cli.SwitchAttr(
                "--history",
                str,
                argname = 'HISTORY_RANGE',
                default = 'none',
                help= """history range to be retrieved (see --help-about history)""")

    @cli.switch(["-z", "--help-about"], str, \
                group = "Meta-switches")
    def help_about(self, topic):
        """Prints help details about a given topic."""
        if topic not in WALT_LOG_SHOW_HELP:
            print 'Sorry, this topic is unknown. Available topics are:'
            print ', '.join(WALT_LOG_SHOW_HELP.keys())
            sys.exit()
        self.help_messages.append(WALT_LOG_SHOW_HELP[topic])

    def analyse_history_range(self):
        MALFORMED=(False,)
        try:
            self.history_range = self.history_range.lower()
            if self.history_range == 'none':
                return True, None
            elif self.history_range == 'full':
                return True, (None, None)
            parts = self.history_range.split(':')
            if len(parts) != 2:
                return MALFORMED
            delays = []
            for part in parts:
                if part == '':
                    delays.append(None)
                elif part.startswith('-'):
                    delays.append(int(part[1:-1]) * \
                            SECONDS_PER_UNIT[part[-1]])
                else:
                    return MALFORMED
            if delays[0] and delays[1]:
                if delays[0] < delays[1]:
                    print 'Issue with the HISTORY_RANGE specified: ' + \
                            'the starting point is newer than the ending point.'
                    return MALFORMED
            return True, tuple(delays)
        except:
            return MALFORMED

    def main(self):
        if len(self.help_messages) > 0:
            for msg in self.help_messages:
                print msg
            return
        if self.realtime == False and self.history_range == 'none':
            print 'You must specify at least 1 of the options --realtime and --history.'
            return
        range_analysis = self.analyse_history_range()
        if not range_analysis[0]:
            print '''Invalid HISTORY_RANGE. See 'walt log show --help-about history' for more info.'''
            return
        history_range = range_analysis[1]
        if history_range:
            with ClientToServerLink() as server:
                num_logs = server.count_logs(history = history_range)
            if num_logs > NUM_LOGS_CONFIRM_TRESHOLD:
                print 'This will display approximately %d log records from history.' % num_logs
                if not confirm():
                    print 'Aborted.'
                    return
        conn = LogsFlowFromServer(conf['server'])
        conn.request_log_dump(history = history_range, realtime = self.realtime)
        while True:
            try:
                record = conn.read_log_record()
                if record == None:
                    break
                print self.format_string.format(**record)
                sys.stdout.flush()
            except KeyboardInterrupt:
                print
                break
            except Exception as e:
                print 'Could not display the log record.'
                print 'Verify your format string.'
                break

