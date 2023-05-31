#!/usr/bin/env python
import os
import pickle
import pty
import shlex
import signal
import sys

from walt.common.io import read_and_copy
from walt.common.tcp import read_pickle
from walt.common.tty import set_tty_size, set_tty_size_raw


class ForkPtyProcessListener(object):
    def __init__(self, slave_pid, env):
        self.slave_pid = slave_pid
        self.env = env

    # let the event loop know what we are reading on
    def fileno(self):
        return self.env.slave_r.fileno()

    # when the event loop detects an event for us, this means
    # the slave proces wrote something on its output
    # we just have to copy this to the user socket
    def handle_event(self, ts):
        return read_and_copy(self.env.slave_r, self.env.client_sock_file)

    def end_child(self):
        try:
            os.kill(self.slave_pid, signal.SIGKILL)
        except OSError:
            pass

    def close(self):
        self.end_child()
        self.env.close()


class ParallelProcessSocketListener(object):
    def __init__(self, ev_loop, sock_file, **kwargs):
        self.ev_loop = ev_loop
        self.params = None
        self.client_sock_file = sock_file
        self.slave_r, self.slave_w = None, None
        self.send_client("READY\n")

    def send_client(self, s):
        self.client_sock_file.write(s.encode("UTF-8"))

    def update_params(self):
        pass  # override in subclasses if needed

    def prepare(self, **params):
        return True  # override in subclasses if needed

    def get_command(self, **params):
        """this should be defined in subclasses"""
        raise NotImplementedError

    def start(self):
        cmd_args = shlex.split(self.params["cmd"])
        env = os.environ.copy()
        if "env" in self.params:
            env.update(self.params["env"])
        if "tty_mode" in self.params and self.params["tty_mode"] is True:
            return self.start_pty(cmd_args, env)
        else:
            return self.start_popen(cmd_args, env)

    def start_pty(self, cmd_args, env):
        # print(f'{self.client_sock_file.fileno()}: start_pty {cmd_args}')
        # fork a child process in its own virtual terminal
        slave_pid, fd_slave = pty.fork()
        # the child (slave process) should execute the command
        if slave_pid == 0:
            # set the window size appropriate for the remote client
            if "win_size" in self.params:
                set_tty_size_raw(sys.stdout.fileno(), self.params["win_size"])
            os.execvpe(cmd_args[0], cmd_args, env)
        # the parent should communicate.
        # use unbuffered communication with the slave process
        self.slave_r = os.fdopen(os.dup(fd_slave), "rb", 0)
        self.slave_w = os.fdopen(fd_slave, "wb", 0)
        # create a new listener on the event loop for reading
        # what the slave process outputs
        process_listener = ForkPtyProcessListener(slave_pid, self)
        self.ev_loop.register_listener(process_listener)

    def start_popen(self, cmd_args, env):
        # For efficiency, we fork a child process which will read & write directly
        # on the socket.
        # print(f'{self.client_sock_file.fileno()}: start_popen {cmd_args}')
        if os.fork() == 0:
            # - child -
            sock_fd = self.client_sock_file.fileno()
            for std_fd in (0, 1, 2):
                os.dup2(sock_fd, std_fd)
            os.close(sock_fd)
            os.execvpe(cmd_args[0], cmd_args, env)
        # - parent -
        # the child will do the work, we are no longer needed,
        # so let the event loop remove us.
        return False

    # let the event loop know what we are reading on
    def fileno(self):
        if self.client_sock_file.closed:
            return None
        return self.client_sock_file.fileno()

    # handle_event() will be called when the event loop detects
    # new input data for us.
    def handle_event(self, ts):
        try:
            if self.params is None:
                # we did not get the parameters yet, let's do it
                self.params = read_pickle(self.client_sock_file)
                if self.params is None:
                    print(f"{self.client_sock_file.fileno()}: malformed params")
                    return False  # issue, this will call self.close()
                self.update_params()
                if self.prepare(**self.params) is False:
                    # print(f'{self.client_sock_file.fileno()}: closing due to params')
                    return False  # issue, this will call self.close()
                self.params["cmd"] = self.get_command(**self.params)
                # we now have all info to start the child process
                return self.start()
            else:
                # otherwise we are all set. Getting here means
                # we got input data or the child process ended.
                # the fact we are still alive and listening implies
                # we are in the tty mode.
                # in this mode input data and window resize events are
                # multiplexed on the socket.
                evt_info = pickle.load(self.client_sock_file)
                if evt_info["evt"] == "input_data":
                    self.slave_w.write(evt_info["data"])
                    self.slave_w.flush()
                elif evt_info["evt"] == "window_resize":
                    win_size = (evt_info["lines"], evt_info["columns"])
                    set_tty_size(self.slave_w.fileno(), win_size)
        except Exception as e:
            print(self, "exception:", repr(e))
            return False  # issue, this will call self.close()

    def close(self):
        if self.client_sock_file:
            self.client_sock_file.close()
            self.client_sock_file = None
        if self.slave_r:
            self.slave_r.close()
            self.slave_r = None
        if self.slave_w:
            self.slave_w.close()
            self.slave_w = None
