#!/usr/bin/env python
import sys, tty, termios, array, fcntl
from walt.client.config import conf
from sys import stdin, stdout
from select import select
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.io import SmartBufferingFileReader, \
                            unbuffered, read_and_copy
from walt.common.tcp import Requests, write_pickle, client_socket
from walt.client import myhelp

SQL_SHELL_MESSAGE = """\
Type \dt for a list of tables.
"""
IMAGE_SHELL_MESSAGE = """\
Notice: this is a limited virtual environment.
Run 'walt --help-about shells' for more info.
"""
NODE_SHELL_MESSAGE = """\
Caution: changes will be lost on next node reboot.
Run 'walt --help-about shells' for more info.
"""

myhelp.register_topic('shells', """
                | walt node shell    | walt image shell
------------------------------------------------------------
persistence     | until the node     | yes
                | reboots (1)        |
------------------------------------------------------------
backend         | the real node      | virtual environment
                |                    | ARM CPU emulation (2)
------------------------------------------------------------
target workflow | testing/debugging  | apply changes
                |                    |
------------------------------------------------------------

(1): Changes are lost on reboot. This ensures that a node booting a
given image will always act the same.

(2): Avoid heavy processing, such as compiling of a large
source code base. In this case, cross-compiling on another machine
and importing the build artefacts in the virtual environment (through
the emulated network) should be the prefered option.
Also, keep in mind that in the virtual environment (docker container)
no services are running (no init process, etc). Actually, the only
process running in this virtual environment when you enter it is the
shell process itself.
""")

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
    def __init__(self, req_id, **params):
        self.tty_settings = TTYSettings()
        # connect
        server_host = conf['server']
        s = client_socket(server_host, WALT_SERVER_TCP_PORT)
        # use unbuffered communication
        self.socket_r = s.makefile('r', 0)
        self.socket_w = s.makefile('w', 0)
        # write request id
        Requests.send_id(self.socket_w, req_id)
        # wait for the READY message from the server
        self.socket_r.readline()
        # send terminal width and provided parameters
        params.update(
            win_size = self.tty_settings.win_size
        )
        write_pickle(params, self.socket_w)
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
    PromptClient(Requests.REQ_SQL_PROMPT).run()

def run_image_shell_prompt(session):
    print IMAGE_SHELL_MESSAGE
    image_fullname, container_name = session.get_parameters()
    PromptClient(Requests.REQ_DOCKER_PROMPT,
                image_fullname = image_fullname,
                container_name = container_name).run()

def run_node_shell(node_ip):
    print NODE_SHELL_MESSAGE
    PromptClient(Requests.REQ_NODE_SHELL, node_ip=node_ip).run()

def run_device_ping(device_ip):
    PromptClient(Requests.REQ_DEVICE_PING, device_ip=device_ip).run()

