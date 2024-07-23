#!/usr/bin/env python
import io
import os
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
IMAGE_SHELL_MESSAGE = """\
Notice: this is a limited virtual environment.
Run 'walt help show shells' for more info.
"""
NODE_SHELL_MESSAGE = """\
Caution: changes outside /persist will be lost on next node reboot.
Run 'walt help show shells' for more info.
"""


class PromptClient(object):
    def __init__(self, req_id, capture_output=False, **params):
        self.capture_output = capture_output
        self.resize_handler_called = False
        if sys.stdout.isatty() and sys.stdin.isatty():
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
                rlist, wlist, elist = select(fds, [], fds)
                if self.tty_mode:
                    self.toggle_sigwinch_mask(signal.SIG_BLOCK)
                if self.resize_handler_called:
                    # select has been interrupted by the SIGWINCH signal
                    self.resize_handler_called = False  # reset for next time
                    continue  # return to select()
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
        if self.capture_output:
            return captured.getvalue()


def run_sql_prompt():
    print(SQL_SHELL_MESSAGE)
    PromptClient(Requests.REQ_SQL_PROMPT).run()


def run_image_shell_prompt(image_fullname, container_name):
    print(IMAGE_SHELL_MESSAGE)
    PromptClient(
        Requests.REQ_DOCKER_PROMPT,
        image_fullname=image_fullname,
        container_name=container_name,
    ).run()


def run_node_cmd(node_ip, cmdargs, ssh_tty, capture_output):
    return PromptClient(
        Requests.REQ_NODE_CMD,
        node_ip=node_ip,
        cmdargs=tuple(cmdargs),
        ssh_tty=ssh_tty,
        capture_output=capture_output,
    ).run()


def run_device_ping(device_ip):
    PromptClient(Requests.REQ_DEVICE_PING, device_ip=device_ip).run()


def run_device_shell(device_ip, user):
    PromptClient(Requests.REQ_DEVICE_SHELL, device_ip=device_ip, user=user).run()
