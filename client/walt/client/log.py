import sys, re, datetime, pickle
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import read_pickle, write_pickle, client_sock_file, \
                            Requests
from plumbum import cli
from walt.client.application import WalTCategoryApplication, WalTApplication
from walt.client.config import conf
from walt.client.link import ClientToServerLink
from walt.client.tools import confirm
from walt.client.timeout import start_timeout, stop_timeout, timeout_reached, cli_timeout_switch

DATE_FORMAT_STRING= '%Y-%m-%d %H:%M:%S'
DATE_FORMAT_STRING_HUMAN= '<YYYY>-<MM>-<DD> <hh>:<mm>:<ss>'
DATE_FORMAT_STRING_EXAMPLE= '2015-09-28 15:16:39'

DEFAULT_FORMAT_STRING= \
   '{timestamp:%H:%M:%S.%f} {sender}.{stream} -> {line}'

SECONDS_PER_UNIT = {'s':1, 'm':60, 'h':3600, 'd':86400}
NUM_LOGS_CONFIRM_TRESHOLD = 1000

MSG_INVALID_CHECKPOINT_NAME="""\
Invalid checkpoint name:
* Only alnum and dash(-) characters are allowed.
* dash(-) is not allowed as the 1st character.
"""

def isatty():
    return sys.stdout.isatty() and sys.stdin.isatty()

def validate_checkpoint_name(name):
    return re.match('^[a-zA-Z0-9]+[a-zA-Z0-9\-]+$', name)

def compute_relative_date(server_time, rel_date):
    try:
        delay = datetime.timedelta(
                seconds = int(rel_date[1:-1]) * \
                    SECONDS_PER_UNIT[rel_date[-1]])
    except:
        print("Invalid relative date. Should be: -<int>[dhms] (e.g. '-6h' for 'six hours ago')")
        sys.exit(1)
    return pickle.dumps(server_time - delay)

class LogsFlowFromServer(object):
    def __init__(self, walt_server_host):
        self.f = client_sock_file(walt_server_host, WALT_SERVER_TCP_PORT)
    def read_log_record(self):
        return read_pickle(self.f)
    def request_log_dump(self, **kwargs):
        Requests.send_id(self.f, Requests.REQ_DUMP_LOGS)
        write_pickle(kwargs, self.f)
    def close(self):
        self.f.close()

class WalTLog(WalTCategoryApplication):
    """management of logs"""
    pass

class WalTLogShowOrWait(WalTApplication):
    """Implements options and features common to "show" and "wait" subcommands"""
    format_string = cli.SwitchAttr(
                "--format",
                str,
                argname = 'LOG_FORMAT',
                default = DEFAULT_FORMAT_STRING,
                help= """format used to print logs (see walt help show log-format)""")
    set_of_nodes = cli.SwitchAttr(
                "--nodes",
                str,
                argname = 'SET_OF_NODES',
                default = 'my-nodes',
                help= """targeted nodes (see walt help show node-terminology)""")
    streams = cli.SwitchAttr(
                "--streams",
                str,
                argname = 'STREAMS_REGEXP',
                default = None,
                help= """selected log streams (as a regular expr.)""")

    @staticmethod
    def analyse_history_range(server, history_range):
        server_time = pickle.loads(server.get_pickled_time())
        MALFORMED=(False,)
        try:
            if history_range.lower() == 'none':
                return True, None
            elif history_range.lower() == 'full':
                return True, (None, None)
            parts = history_range.split(':')
            if len(parts) != 2:
                return MALFORMED
            history = []
            for part in parts:
                if part == '':
                    history.append(None)
                elif part.startswith('-'):
                    rel_date = compute_relative_date(server_time, part)
                    history.append(rel_date)
                elif validate_checkpoint_name(part):
                    cptime = server.get_pickled_checkpoint_time(part)
                    if cptime == None:
                        return MALFORMED
                    history.append(cptime)
                else:
                    return MALFORMED
            if history[0] and history[1]:
                if pickle.loads(history[0]) > pickle.loads(history[1]):
                    print('Issue with the HISTORY_RANGE specified: ' + \
                            'the starting point is newer than the ending point.')
                    return MALFORMED
            return True, tuple(history)
        except Exception as e:
            return MALFORMED

    @staticmethod
    def verify_regexps(*regexps):
        for regexp in regexps:
            if regexp is None:
                continue
            try:
                re.compile(regexp)
            except:
                print('Invalid regular expression: %s.' % regexp)
                return False
        return True

    @staticmethod
    def start_streaming(format_string, history_range, realtime, senders, streams,
                        logline_regexp, stop_test, timeout = -1):
        conn = LogsFlowFromServer(conf['server'])
        conn.request_log_dump(  history = history_range,
                                realtime = realtime,
                                senders = senders,
                                streams = streams,
                                logline_regexp = logline_regexp)
        if timeout > 0:
            start_timeout(timeout)
        while True:
            try:
                record = conn.read_log_record()
                # sigalarm is caught by pickle, it will just abort the read
                # and record will be None.
                # Since we cannot get a TimeoutException, we check with timeout_reached().
                if timeout > 0 and timeout_reached():
                    print('Timeout was reached.')
                    break
                if record == None:
                    break
                print(format_string.format(**record))
                sys.stdout.flush()
                if stop_test is not None and stop_test(**record):
                    break
            except KeyboardInterrupt:
                print()
                break
            except Exception as e:
                print('Could not display the log record.')
                print('Verify your format string.')
                break
        if timeout > 0:
            stop_timeout()

@WalTLog.subcommand("show")
class WalTLogShow(WalTLogShowOrWait):
    """Dump logs on standard output"""
    realtime = cli.Flag(
                "--realtime",
                default = False,
                help= """enable realtime mode (see walt help show log-realtime)""")
    history_range = cli.SwitchAttr(
                "--history",
                str,
                argname = 'HISTORY_RANGE',
                default = 'none',
                help= """history range to be retrieved (see walt help show log-history)""")

    def main(self, logline_regexp = None):
        if self.realtime == False and self.history_range == 'none':
            print('You must specify at least 1 of the options --realtime and --history.')
            print("See 'walt help show log-realtime' and 'walt help show log-history' for more info.")
            return
        if not WalTLogShowOrWait.verify_regexps(self.streams, logline_regexp):
            return
        with ClientToServerLink() as server:
            senders = server.parse_set_of_nodes(self.set_of_nodes)
            if senders == None:
                return
            range_analysis = WalTLogShowOrWait.analyse_history_range(server, self.history_range)
            if not range_analysis[0]:
                print('''Invalid HISTORY_RANGE. See 'walt help show log-history' for more info.''')
                return
            history_range = range_analysis[1]
            # Note : if a regular expression is specified, we do not bother computing the number
            # of log records, because this computation would be too expensive, and the number of
            # matching lines is probably low.
            if history_range and logline_regexp is None and isatty():
                num_logs = server.count_logs(history = history_range, senders = senders, streams = self.streams)
                if num_logs > NUM_LOGS_CONFIRM_TRESHOLD:
                    print('This will display approximately %d log records from history.' % num_logs)
                    if not confirm():
                        return
        WalTLogShowOrWait.start_streaming(self.format_string, history_range, self.realtime,
                                            senders, self.streams, logline_regexp, None)

@WalTLog.subcommand("add-checkpoint")
class WalTLogAddCheckpoint(WalTApplication):
    """Record a checkpoint (reference point in time)"""
    date = cli.SwitchAttr("--date", str, default=None,
                          help="specify date (see walt help show log-checkpoint)")
    def main(self, checkpoint_name):
        with ClientToServerLink() as server:
            if self.date:
                if self.date.startswith('-'):
                    server_time = pickle.loads(server.get_pickled_time())
                    self.date = compute_relative_date(server_time, self.date)
                else:
                    try:
                        self.date = pickle.dumps(datetime.datetime.strptime(\
                                        self.date, DATE_FORMAT_STRING))
                    except:
                        print('Could not parse the date specified.')
                        print('Expected format is: %s' % DATE_FORMAT_STRING_HUMAN)
                        print('Example: %s' % DATE_FORMAT_STRING_EXAMPLE)
                        return
            if not validate_checkpoint_name(checkpoint_name):
                sys.stderr.write(MSG_INVALID_CHECKPOINT_NAME)
                return
            server.add_checkpoint(checkpoint_name, self.date)

@WalTLog.subcommand("remove-checkpoint")
class WalTLogRemoveCheckpoint(WalTApplication):
    """Remove a checkpoint"""
    def main(self, checkpoint_name):
        with ClientToServerLink() as server:
            server.remove_checkpoint(checkpoint_name)

@WalTLog.subcommand("list-checkpoints")
class WalTLogListCheckpoints(WalTApplication):
    """List checkpoints"""
    def main(self):
        with ClientToServerLink() as server:
            server.list_checkpoints()

@WalTLog.subcommand("wait")
class WalTLogWait(WalTLogShowOrWait):
    """Wait for a given log line"""
    mode = cli.SwitchAttr(
                "--mode",
                cli.Set("ALL", "ANY", case_sensitive = False),
                argname = 'MODE',
                default = 'ANY',
                help= """specify mode (see walt help show log-wait)""")
    time_margin = cli.SwitchAttr(
                "--time-margin",
                int,
                argname = 'SECONDS',
                default = 0,
                help= """also look in recent past logs if they matched""")
    timeout = cli_timeout_switch()

    def main(self, logline_regexp):
        if not WalTLogShowOrWait.verify_regexps(self.streams, logline_regexp):
            return
        with ClientToServerLink() as server:
            senders = server.parse_set_of_nodes(self.set_of_nodes)
            if senders == None:
                return
            if self.time_margin != 0:
                history_range = '-%ds:' % self.time_margin
                range_analysis = WalTLogShowOrWait.analyse_history_range(server, history_range)
                history_range = range_analysis[1]
            else:
                history_range = None
        if self.mode == 'ANY':
            # as soon as a logline matches, we stop
            def stop_test(**record):
                return True
        else:
            # we stop when all nodes have emitted a matching logline
            missing_senders = set(senders)
            def stop_test(**record):
                missing_senders.discard(record['sender'])
                if len(missing_senders) == 0:
                    return True     # yes, we should stop
                else:
                    return False    # no, we are not done yet
        WalTLogShowOrWait.start_streaming(self.format_string, history_range, True,
                                    senders, self.streams, logline_regexp, stop_test, self.timeout)
