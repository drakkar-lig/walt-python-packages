#!/usr/bin/env python
import io
import os
import re
import secrets
import signal
import socket
import sys
from select import select
from socket import SHUT_WR
from sys import stdin, stdout

from walt.client.link import connect_to_tcp_server
from walt.common.io import read_and_copy, unbuffered
from walt.common.tcp import Requests, write_pickle, MyPickle as pickle

SQL_SHELL_MESSAGE = """\
Type \\dt for a list of tables.
"""


# when output bytes are held back by ExitStatusFilter (because they could
# be the beginning of the exit status line), they are released if no more
# data arrives within this delay (the server writes the exit status line
# at once, at the end).
EXIT_STATUS_HOLD_DELAY = 0.05


class ExitStatusFilter:
    """Output filter removing the exit status line the server writes at the
       end of the output of a command (see EXIT_STATUS_WRAPPER on server side).
       Output bytes are passed through immediately, except a final part which
       could be the beginning of this line. This line starts with a NUL byte,
       so this rarely happens, and these bytes are released by release_held()
       if nothing else arrives soon."""

    def __init__(self, out, marker):
        self._out = out
        self._marker = marker
        self._held = b""
        self._trailer_re = re.compile(re.escape(marker) + rb"(\d+)\r?\n")
        self.exit_status = None

    def write(self, data):
        buf = self._held + data
        idx = buf.find(self._marker)
        if idx >= 0:
            # keep the end of the output (from the marker) until EOF
            pass_len = idx
        else:
            # keep the longest end of buf which is a prefix of the marker
            pass_len = len(buf)
            for k in range(min(len(self._marker) - 1, len(buf)), 0, -1):
                if buf.endswith(self._marker[:k]):
                    pass_len = len(buf) - k
                    break
        self._out.write(buf[:pass_len])
        self._held = buf[pass_len:]

    def flush(self):
        self._out.flush()

    def holds_partial_marker(self):
        return len(self._held) > 0 and not self._held.startswith(self._marker)

    def release_held(self):
        # called when nothing arrived for a short time: the held bytes were
        # not the beginning of the exit status line.
        if self.holds_partial_marker():
            self._out.write(self._held)
            self._out.flush()
            self._held = b""

    def end(self):
        m = self._trailer_re.fullmatch(self._held)
        if m is None:
            # no exit status line (the connection ended abnormally):
            # output what we held
            self._out.write(self._held)
        else:
            self.exit_status = int(m.group(1))
        self._held = b""
        self._out.flush()


# exit status when the server did not report the exit status of a command,
# i.e. when the connection ended abnormally (like ssh in this case).
UNKNOWN_EXIT_STATUS = 255


def isatty():
    return stdout.isatty() and stdin.isatty()


class PromptClient(object):
    def __init__(self, req_id, capture_output=False, get_exit_status=False,
                 **params):
        self.capture_output = capture_output
        self.exit_status_marker = None
        self.exit_status = None
        if get_exit_status:
            # ask the server to write the exit status of the command at the
            # end of its output, after this random marker.
            marker = f"__WALT_EXIT_STATUS_{secrets.token_hex(16)}__"
            params.update(exit_status_marker=marker)
            # (the server writes a NUL byte before the marker, see
            # ExitStatusFilter)
            self.exit_status_marker = b"\x00" + marker.encode("ascii")
        self.resize_handler_called = False
        if isatty():
            self.tty_mode = True
            # importing a module in the resize_handler() is dangerous
            # because two signals could be raised in a short interval,
            # and the import of the first call could be interrupted.
            # so let's do it now.
            from walt.common.term import TTYSettings
            self.tty_settings = TTYSettings()
            # send terminal width and provided parameters
            params.update(win_size=self.tty_settings.win_size)
            if "TERM" in os.environ:
                params.update(env={"TERM": os.environ["TERM"]})
        else:
            self.tty_mode = False
        # tell server whether we are on a tty
        params.update(tty_mode=self.tty_mode)
        # connect
        self.sock_file = connect_to_tcp_server()
        # write request id
        Requests.send_id(self.sock_file, req_id)
        # wait for the READY message from the server
        self.sock_file.readline()
        write_pickle(params, self.sock_file)
        # make stdin unbuffered
        self.stdin_reader = unbuffered(stdin, "rb")

    def resize_handler(self, signum, frame):
        self.resize_handler_called = True
        if self.tty_mode:
            # the python doc recommends using shutil.get_terminal_size()
            # which may internally call os.get_terminal_size(). But it will
            # use LINES and COLUMNS environment variables if available,
            # and these variables may be wrong (not updated) in some cases.
            # we prefer to try querying the terminal first (i.e., call
            # os.get_terminal_size()), and if this fails, fallback to
            # reasonable defaults using shutil.get_terminal_size().
            try:
                termsize = os.get_terminal_size()
            except OSError:
                import shutil
                termsize = shutil.get_terminal_size()
            buf = pickle.dumps(
                {
                    "evt": "window_resize",
                    "lines": termsize.lines,
                    "columns": termsize.columns,
                }
            )
            self.sock_file.write(buf)
            self.sock_file.flush()

    def toggle_sigwinch_mask(self, action):
        signal.pthread_sigmask(action, set([signal.SIGWINCH]))

    def run(self):
        if self.capture_output:
            captured = io.BytesIO()
            out_buffer = captured
        else:
            out_buffer = stdout.buffer
        status_filter = None
        if self.exit_status_marker is not None:
            status_filter = ExitStatusFilter(out_buffer, self.exit_status_marker)
            out_buffer = status_filter
        # we will wait on 2 file descriptors
        fds = [stdin, self.sock_file]

        # this is the main trick when trying to provide a virtual
        # terminal remotely: the client should set its own terminal
        # in 'raw' mode, in order to avoid interpreting any escape
        # sequence (ctrl-r, etc.). These sequences should just be
        # forwarded up to the terminal running on the server, and
        # this remote terminal will interpret them.
        # Also, echo-ing what is typed should be disabled at the
        # client side, otherwise it would be echo-ed twice.
        # It is better to consider that the server terminal will
        # handle all outputs, otherwise the synchronization between
        # the output coming from the client (echo) and from the
        # server (command outputs, prompts) will not be perfect
        # because of network latency. Thus we let the server terminal
        # handle the echo.
        if self.tty_mode:
            self.tty_settings.set_raw_no_echo()
            signal.signal(signal.SIGWINCH, self.resize_handler)
        try:
            while True:
                if self.tty_mode:
                    self.toggle_sigwinch_mask(signal.SIG_UNBLOCK)
                timeout = None
                if status_filter is not None and \
                        status_filter.holds_partial_marker():
                    timeout = EXIT_STATUS_HOLD_DELAY
                rlist, wlist, elist = select(fds, [], fds, timeout)
                if self.tty_mode:
                    self.toggle_sigwinch_mask(signal.SIG_BLOCK)
                if self.resize_handler_called:
                    # select has been interrupted by the SIGWINCH signal
                    self.resize_handler_called = False  # reset for next time
                    continue  # return to select()
                if len(rlist) == 0 and len(elist) == 0:
                    # timeout: release the bytes held by the status filter
                    status_filter.release_held()
                    continue
                if len(elist) > 0 and len(rlist) == 0:
                    break
                fd = rlist[0].fileno()
                if fd == self.sock_file.fileno():
                    if read_and_copy(self.sock_file, out_buffer) is False:
                        break
                else:
                    try:
                        buf = self.stdin_reader.read(4096)
                        if buf == b"":
                            # stdin was probably closed, inform the server input is
                            # ending and continue by reading socket only
                            self.sock_file.shutdown(SHUT_WR)
                            fds = [self.sock_file]
                            continue
                        if self.tty_mode:
                            buf = pickle.dumps(
                                {"evt": "input_data", "data": buf}
                            )
                        self.sock_file.write(buf)
                        self.sock_file.flush()
                    except socket.error:
                        break
        finally:
            if self.tty_mode:
                self.tty_settings.restore()
        if self.exit_status_marker is not None:
            out_buffer.end()
            self.exit_status = out_buffer.exit_status
        if self.capture_output:
            return captured.getvalue()


def run_with_exit_status(req_id, **params):
    """Run a PromptClient session and return the exit status of the command
       run on server side."""
    client = PromptClient(req_id, get_exit_status=True, **params)
    client.run()
    if client.exit_status is None:
        return UNKNOWN_EXIT_STATUS
    return client.exit_status


def run_sql_prompt():
    print(SQL_SHELL_MESSAGE)
    return run_with_exit_status(Requests.REQ_SQL_PROMPT)


def run_image_shell_prompt(image_fullname, container_name):
    # note: we do not use the exit status of the image shell session: the
    # last command typed by the user may have failed, but the user may
    # still want to save the image.
    PromptClient(
        Requests.REQ_DOCKER_PROMPT,
        image_fullname=image_fullname,
        container_name=container_name,
    ).run()




def run_node_cmd(node_ip, cmdargs, ssh_tty, capture_output):
    """Run a command on a node. Return its output if capture_output is True,
       otherwise its exit status."""
    client = PromptClient(
        Requests.REQ_NODE_CMD,
        node_ip=node_ip,
        cmdargs=tuple(cmdargs),
        ssh_tty=ssh_tty,
        capture_output=capture_output,
        get_exit_status=True,
    )
    output = client.run()
    if capture_output:
        return output
    if client.exit_status is None:
        return UNKNOWN_EXIT_STATUS
    return client.exit_status


def run_device_ping(device_ip):
    return run_with_exit_status(Requests.REQ_DEVICE_PING, device_ip=device_ip)


def run_device_shell(device_ip, user):
    return run_with_exit_status(Requests.REQ_DEVICE_SHELL,
                                device_ip=device_ip, user=user)
