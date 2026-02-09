import datetime
import os
import re
import socket
import sys
from select import select
from time import time, sleep

from walt.client.log import LogsFlowFromServer
from walt.common.term import TTYSettings, clear_screen
from walt.common.term import alternate_screen_buffer, hidden_cursor
from walt.common.formatting import framed

WELCOME_MESSAGE = """
This will start the virtual node console viewer.
When you want to exit, type <ctrl-a> <d>.
See 'walt help show node-console' for more info.

Type <enter> to validate, or <ctrl-c> to abort: """

TIMEOUT_DETECT_END_OF_REPLAY = 0.5
TRANSIENT_MESSAGE_DELAY_PER_CHAR = 0.064


class VirtualClock:
    MAX_CLOCK_WAIT = 2.0
    CLOCK_SPEEDUP = 1.0
    def __init__(self):
        self._server_t = None
    def get_delay_to_server_time(self, server_t):
        if self._server_t is None:
            self._server_t = server_t
            return 0
        else:
            delay = (server_t - self._server_t)
            delay = min(delay, VirtualClock.MAX_CLOCK_WAIT)
            self._server_t = server_t
            return delay / VirtualClock.CLOCK_SPEEDUP


class EndOfConsole(Exception):
    pass


def wait_event(fds, timeout):
    rlist, wlist, elist = select(fds, [], fds, timeout)
    if len(elist) > 0 and len(rlist) == 0:
        raise EndOfConsole()
    if len(rlist) == 0:
        return None   # timed out
    return rlist[0]


class StdinReader:
    def __init__(self):
        self._buf = b""
    def read_more(self):
        try:
            buf = os.read(0, 4096)
        except socket.error:
            raise EndOfConsole()
        if buf == b"":  # stdin closed
            raise EndOfConsole()
        self._buf += buf
        outbuf = b""
        while len(self._buf) > 0:
            if (self._buf.startswith(b"\x01a") or
                self._buf.startswith(b"\x01\x01")):
                # <ctrl-a> <a> or <ctrl-a> <ctrl-a>: send <ctrl-a>
                outbuf += b"\x01"
                self._buf = self._buf[2:]
            elif self._buf.startswith(b"\x01d"):
                # <ctrl-a> <d>: disconnect
                raise EndOfConsole()
            elif self._buf.startswith(b"\x01"):
                if len(self._buf) > 1:
                    # <ctrl-a> <other-key>: unknown shortcut, ignore
                    self._buf = self._buf[2:]
                else:
                    # <ctrl-a> and end of input, wait for next key
                    break
            else:
                # random char
                outbuf += self._buf[0:1]
                self._buf = self._buf[1:]
        return outbuf


def sleep_or_end_console(delay, stdin_reader):
    while True:
        t0 = time()
        fd = wait_event([0], delay)
        t1 = time()
        delay -= (t1 - t0)
        delay = max(0., delay)
        if fd is None:
            return
        else:  # new input from stdin
            # we ignore user input, except <ctrl-a>+<d>
            # which would throw and EndOfConsole() exception.
            stdin_reader.read_more()


def console_transient_message(tty_settings, msg, stdin_reader):
    screen_height, screen_width = tty_settings.rows, tty_settings.cols
    box = framed("Note", msg)
    box_lines = box.splitlines()
    box_height, box_width = len(box_lines), len(box_lines[0])
    padding_height = ((screen_height - box_height)//2) * '\n'
    padding_width = ((screen_width - box_width)//2) * ' '
    box = "\r\n".join(f"{padding_width}{line}" for line in box_lines)
    with alternate_screen_buffer():
        with hidden_cursor():
            clear_screen()
            print(padding_height + box + "\r\n")
            delay = TRANSIENT_MESSAGE_DELAY_PER_CHAR * len(msg)
            sleep_or_end_console(delay, stdin_reader)


def wait_user_exit(stdin_reader, **kwargs):
    # Just wait until the user types "ctrl-a d".
    while True:
        stdin_reader.read_more()


def read_next_chunk(conn, re_escape_filter):
    record = conn.read_log_record()
    if record is None:
        return None, None
    chunk = eval(record["line"])
    chunk = re_escape_filter.sub(b"", chunk)
    record_t = record["timestamp"].timestamp()
    return record_t, chunk


def replay_console_loop(conn, stdin_reader, re_escape_filter, **kwargs):
    vclock = VirtualClock()
    started_receiving_replay_logs = False
    conn_fd = conn.fileno()
    replay_delay, replay_delay_chunk = None, None
    while True:
        if replay_delay is None:
            # no replay delay: listen on both stdin and incoming logs
            if started_receiving_replay_logs:
                timeout = TIMEOUT_DETECT_END_OF_REPLAY
            else:
                timeout = None
            fd = wait_event([0, conn_fd], timeout)
            if fd == None:
                # timed out receiving logs => end of replay logs
                return
        else:
            # during "replay_delay" we only listen on stdin
            t0 = time()
            fd = wait_event([0], replay_delay)
            t1 = time()
            replay_delay -= (t1 - t0)
            replay_delay = max(0., replay_delay)
            if fd is None:
                # end of the replay delay:
                # write the delayed chunk and disable this mode
                os.write(1, replay_delay_chunk)
                replay_delay, replay_delay_chunk = None, None
                continue
        if fd == conn_fd:  # new console log from server
            record_t, chunk = read_next_chunk(conn, re_escape_filter)
            if chunk is None:
                return    # end of replay logs
            started_receiving_replay_logs = True
            # introduce a delay to mimic the pace of log timestamps
            # we will listen on stdin only during this delay.
            replay_delay = vclock.get_delay_to_server_time(record_t)
            replay_delay_chunk = chunk
        if fd == 0:  # new input from stdin
            # we ignore user input in replay mode, except <ctrl-a>+<d>
            # which would throw and EndOfConsole() exception.
            stdin_reader.read_more()


def interactive_console_loop(conn, re_escape_filter, stdin_reader,
                             server, node_info, **kwargs):
    conn_fd = conn.fileno()
    while True:
        fd = wait_event([0, conn_fd], None)
        if fd == conn_fd:
            _, chunk = read_next_chunk(conn, re_escape_filter)
            if chunk is None:
                raise EndOfConsole()
            os.write(1, chunk)
        else:  # stdin
            buf = stdin_reader.read_more()
            if len(buf) > 0:
                server.vnode_console_input(node_info["mac"], buf)


def console_loops(tty_settings, replay_requested, num_replay_logs,
                  realtime, **kwargs):
    re_escape_filter = re.compile(r"\x1b(c|\[2J)".encode("ascii"))
    stdin_reader = StdinReader()
    all_kwargs = dict(
            re_escape_filter = re_escape_filter,
            stdin_reader = stdin_reader,
            **kwargs
    )
    try:
        if num_replay_logs > 0:
            msg = ("Replaying past console traffic.\n"
                   "No interaction available in this mode.")
            console_transient_message(tty_settings, msg, stdin_reader)
            replay_console_loop(**all_kwargs)
        if realtime == True:
            if replay_requested:
                if num_replay_logs > 0:
                    msg = "Now switching to realtime interaction."
                else:
                    msg = ("No recorded console traffic in the specified "
                           "replay range.\n"
                           "Switching to realtime interaction directly.")
                console_transient_message(tty_settings, msg, stdin_reader)
            interactive_console_loop(**all_kwargs)
        else:
            msg = ("End of the replay. "
                   "We will now display the last screen state.\n"
                   "Type <ctrl-a> <d> to exit.")
            console_transient_message(tty_settings, msg, stdin_reader)
            wait_user_exit(**all_kwargs)
    except EndOfConsole:
        return


def run_node_console(server, node_info, realtime, replay_range):
    node_name = node_info["name"]
    logs_filter = dict(
        issuers=(node_name,),
        streams_regexp="^virtualconsole$",
        logline_regexp=None,
    )
    # count the number of logs coming from history
    if replay_range:
        replay_requested = True
        num_replay_logs = server.count_logs(history=replay_range,
                                            **logs_filter)
        if num_replay_logs == 0:
            # no logs in given history range
            if realtime:
                # we'll continue because --realtime was specified too,
                # but no need to re-do a query for historical data then.
                replay_range = None
            else:
                print("No console traffic was recorded during "
                      "the specified replay range.")
                return False
    else:
        replay_requested = False
        num_replay_logs = 0
    # establish logs connection to server
    conn = LogsFlowFromServer()
    conn.request_log_dump(
        history=replay_range,
        realtime=realtime,
        **logs_filter)
    # run loop
    print(WELCOME_MESSAGE, end="")
    sys.stdout.flush()
    input()
    print("OK, connecting.")
    tty_settings = TTYSettings()
    try:
        clear_screen()
        sys.stdout.flush()
        tty_settings.set_raw_no_echo()
        tty_settings.set_title(f"{node_name} console")
        console_loops(server=server,
                      conn=conn,
                      node_info=node_info,
                      realtime=realtime,
                      replay_requested=replay_requested,
                      num_replay_logs=num_replay_logs,
                      tty_settings=tty_settings)
    finally:
        tty_settings.restore()
        print("\x1bc")  # full terminal reset
        print("Disconnected.")
