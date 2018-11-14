#!/usr/bin/env python
import os, pty, shlex, fcntl, termios, sys, threading, socket, signal
from subprocess import Popen, STDOUT
from walt.common.io import SmartFile, read_and_copy
from walt.common.tcp import read_pickle
from walt.common.tty import set_tty_size_raw
from walt.common.tools import set_close_on_exec

class ForkPtyProcessListener(object):
    def __init__(self, slave_pid, env):
        self.slave_pid = slave_pid
        self.env = env
    # let the event loop know what we are reading on
    def fileno(self):
        return self.env.slave_sock_file.fileno()
    # when the event loop detects an event for us, this means
    # the slave proces wrote something on its output
    # we just have to copy this to the user socket
    def handle_event(self, ts):
        return read_and_copy(
                self.env.slave_sock_file, self.env.client_sock_file)
    def end_child(self):
        try:
            os.kill(self.slave_pid, signal.SIGTERM)
        except OSError:
            pass
        os.wait()   # wait for child's end
    def close(self):
        self.end_child()
        self.env.close()

class ParallelProcessSocketListener(object):
    def __init__(self, ev_loop, sock_file, **kwargs):
        self.ev_loop = ev_loop
        self.params = None
        self.client_sock_file = sock_file
        self.slave_sock_file = None
        self.send_client('READY\n')
    def send_client(self, s):
        self.client_sock_file.write(s)
    def update_params(self):
        pass  # override in subclasses if needed
    def prepare(self, **params):
        return True  # override in subclasses if needed
    def get_command(self, **params):
        '''this should be defined in subclasses'''
        raise NotImplementedError
    def start(self):
        cmd_args = shlex.split(self.params['cmd'])
        env = os.environ.copy()
        if 'env' in self.params:
            env.update(self.params['env'])
        if 'want_tty' in self.params and self.params['want_tty'] \
                and 'client_tty' in self.params and self.params['client_tty']:
            self.start_pty(cmd_args, env)
        else:
            self.start_popen(cmd_args, env)
    def start_pty(self, cmd_args, env):
        # fork a child process in its own virtual terminal
        slave_pid, fd_slave = pty.fork()
        # the child (slave process) should execute the command
        if slave_pid == 0:
            # set the window size appropriate for the remote client
            if 'win_size' in self.params:
                set_tty_size_raw(sys.stdout.fileno(), self.params['win_size'])
            os.execvpe(cmd_args[0], cmd_args, env)
        # the parent should communicate.
        # use unbuffered communication with the slave process
        slave_r = os.fdopen(os.dup(fd_slave), 'r', 0)
        slave_w = os.fdopen(os.dup(fd_slave), 'w', 0)
        self.slave_sock_file = SmartFile(slave_r, slave_w)
        # create a new listener on the event loop for reading
        # what the slave process outputs
        process_listener = ForkPtyProcessListener(slave_pid, self)
        self.ev_loop.register_listener(process_listener)
    def start_popen(self, cmd_args, env):
        # For efficiency, we let the popen object read directly from the socket.
        # Thus the ev_loop should not longer detect input data on this socket,
        # it should only detect errors, that is why we call update_listener() below.
        set_close_on_exec(self.client_sock_file, False)
        self.popen = Popen(cmd_args, env=env, bufsize=1024*1024,
                        stdin=self.client_sock_file, stdout=self.client_sock_file, stderr=STDOUT)
        set_close_on_exec(self.client_sock_file, True)
        self.ev_loop.update_listener(self, 0)
        self.popen_set_finalize_callback()
    # when the popen object exits, close its output in order
    # to notify the end of transmission to the client.
    def popen_set_finalize_callback(self):
        def monitor_popen(popen, client_sock_file):
            popen.wait()
            client_sock_file.close()
            return
        self.popen.monitor_thread = threading.Thread(
                                target=monitor_popen,
                                args=(self.popen, self.client_sock_file))
        self.popen.monitor_thread.start()
    # let the event loop know what we are reading on
    def fileno(self):
        if self.client_sock_file.closed:
            return None
        return self.client_sock_file.fileno()
    # handle_event() will be called when the event loop detects
    # new input data for us.
    def handle_event(self, ts):
        if self.params == None:
            # we did not get the parameters yet, let's do it
            self.params = read_pickle(self.client_sock_file)
            if self.params == None:
                self.close()    # issue
                return False
            self.update_params()
            if self.prepare(**self.params) == False:
                self.close()    # issue
                return False
            self.params['cmd'] = self.get_command(**self.params)
            # we now have all info to start the child process
            self.start()
        else:
            # otherwise we are all set. Thus, getting input data means
            # the user wrote something on the prompt (i.e. the socket)
            # we just have to copy this to the slave process input
            return read_and_copy(
                self.client_sock_file, self.slave_sock_file)
    def close(self):
        if self.client_sock_file:
            self.client_sock_file.close()
            self.client_sock_file = None
        if self.slave_sock_file:
            self.slave_sock_file.close()
            self.slave_sock_file = None

