#!/usr/bin/env python
import sys, tty, termios
from walt.client.config import conf
from sys import stdin, stdout
from select import poll
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.io import POLL_OPS_READ, SmartBufferingFileReader, \
                            is_read_event_ok, unbuffered, \
                            read_and_copy
from walt.common.tcp import REQ_SQL_PROMPT, REQ_DOCKER_PROMPT, \
                            REQ_NODE_SHELL, \
                            write_pickle, client_socket

class TTYSettings(object):
    def __init__(self):
        self.tty_fd = sys.stdout.fileno()
        # save
        self.saved = termios.tcgetattr(self.tty_fd)
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

class PromptClient(object):
    def __init__(self, req_id, request_finalize_func = None):
        # connect
        server_host = conf['server']
        s = client_socket(server_host, WALT_SERVER_TCP_PORT)
        # use unbuffered communication
        self.socket_r = s.makefile('r', 0)
        self.socket_w = s.makefile('w', 0)
        # write request id, and finalize request if needed
        write_pickle(req_id, self.socket_w)
        if request_finalize_func != None:
            request_finalize_func(self.socket_w)
        # provide read_available() method
        self.stdin_reader = SmartBufferingFileReader(unbuffered(stdin, 'r'))
        self.socket_reader = SmartBufferingFileReader(self.socket_r)
        # we will wait on 2 file descriptors
        self.poller = poll()
        self.poller.register(stdin, POLL_OPS_READ)
        self.poller.register(self.socket_r, POLL_OPS_READ)

    def run(self):
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
        tty_settings = TTYSettings()
        tty_settings.set_raw_no_echo()
        try:
            while True:
                fd, ev = self.poller.poll()[0]
                if not is_read_event_ok(ev):
                    break
                if fd == self.socket_r.fileno():
                    if read_and_copy(self.socket_reader, stdout) == False:
                        break
                else:
                    if read_and_copy(self.stdin_reader, self.socket_w) == False:
                        break
        finally:
            tty_settings.restore()

def run_sql_prompt():
    PromptClient(REQ_SQL_PROMPT).run()

def run_modify_image_prompt(session):
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
    def request_finalize(socket_w):
        write_pickle(node_ip, socket_w)
    PromptClient(REQ_NODE_SHELL, request_finalize).run()

