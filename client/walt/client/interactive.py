#!/usr/bin/env python
import sys, tty, termios, array, fcntl
from walt.client.config import conf
from sys import stdin, stdout
from select import select
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.io import SmartBufferingFileReader, \
                            unbuffered, read_and_copy
from walt.common.tcp import REQ_SQL_PROMPT, REQ_DOCKER_PROMPT, \
                            REQ_NODE_SHELL, REQ_DEVICE_PING, \
                            write_pickle, client_socket

SQL_SHELL_MESSAGE = """\
Type \dt for a list of tables.
"""
IMAGE_SHELL_MESSAGE = """\
Notice: this is a limited virtual environment.
Run 'walt --help-shell' for more info.
"""
NODE_SHELL_MESSAGE = """\
Caution: changes will be lost on next node reboot.
Run 'walt --help-shell' for more info.
"""

class TTYSettings(object):
    def __init__(self):
        self.tty_fd = sys.stdout.fileno()
        # save
        self.saved = termios.tcgetattr(self.tty_fd)
        self.win_size = self.get_win_size()
    def set_raw_no_echo(self):
        # set raw mode
        tty.setraw(self.tty_fd, termios.TCSADRAIN)
        # disable echo
        new = termios.tcgetattr(self.tty_fd)
        new[3] &= ~termios.ECHO
        termios.tcsetattr(self.tty_fd, termios.TCSADRAIN, new)
    def restore(self):
        # return saved conf
        termios.tcsetattr(self.tty_fd, termios.TCSADRAIN, self.saved)
    def get_win_size(self):
        buf = array.array('h', [0, 0, 0, 0])
        fcntl.ioctl(self.tty_fd, termios.TIOCGWINSZ, buf, True)
        return buf

class PromptClient(object):
    def __init__(self, req_id, request_finalize_func = None):
        self.tty_settings = TTYSettings()
        # connect
        server_host = conf['server']
        s = client_socket(server_host, WALT_SERVER_TCP_PORT)
        # use unbuffered communication
        self.socket_r = s.makefile('r', 0)
        self.socket_w = s.makefile('w', 0)
        # write request id, and finalize request if needed
        write_pickle(req_id, self.socket_w)
        write_pickle(self.tty_settings.win_size, self.socket_w)
        if request_finalize_func != None:
            request_finalize_func(self.socket_w)
        # provide read_available() method
        self.stdin_reader = SmartBufferingFileReader(unbuffered(stdin, 'r'))
        self.socket_reader = SmartBufferingFileReader(self.socket_r)

    def run(self):
        # we will wait on 2 file descriptors
        select_args = [ [ stdin, self.socket_r ], [], [ stdin, self.socket_r ] ]

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
        self.tty_settings.set_raw_no_echo()
        try:
            while True:
                rlist, wlist, elist = select(*select_args)
                if len(elist) > 0:
                    break
                fd = rlist[0].fileno()
                if fd == self.socket_r.fileno():
                    if read_and_copy(self.socket_reader, stdout) == False:
                        break
                else:
                    if read_and_copy(self.stdin_reader, self.socket_w) == False:
                        break
        finally:
            self.tty_settings.restore()

def run_sql_prompt():
    print SQL_SHELL_MESSAGE
    PromptClient(REQ_SQL_PROMPT).run()

def run_image_shell_prompt(session):
    print IMAGE_SHELL_MESSAGE
    # caution with deadlocks.
    # the server will not be able to initialize the prompt
    # connection and respond to RPyC requests at the same
    # time (and 'session' is a remote RPyC object).
    # So calling get_parameters() in request_finalize()
    # would not be a good idea.
    parameters = session.get_parameters()
    def request_finalize(socket_w):
        write_pickle(parameters, socket_w)
    PromptClient(REQ_DOCKER_PROMPT, request_finalize).run()

def run_node_shell(node_ip):
    print NODE_SHELL_MESSAGE
    def request_finalize(socket_w):
        write_pickle(node_ip, socket_w)
    PromptClient(REQ_NODE_SHELL, request_finalize).run()

def run_device_ping(device_ip):
    def request_finalize(socket_w):
        write_pickle(device_ip, socket_w)
    PromptClient(REQ_DEVICE_PING, request_finalize).run()

