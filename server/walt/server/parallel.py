#!/usr/bin/env python
import os, pty, shlex, uuid, fcntl, termios, sys, threading
from subprocess import Popen, PIPE, STDOUT
from walt.common.io import SmartBufferingFileReader, \
                            unbuffered, read_and_copy
from walt.common.tcp import Requests, read_pickle

class ForkPtyProcessListener(object):
    def __init__(self, slave_r, slave_w, sock_file):
        self.slave_r = slave_r
        self.slave_w = slave_w
        self.sock_file = sock_file
        self.slave_reader = SmartBufferingFileReader(slave_r)
    # let the event loop know what we are reading on
    def fileno(self):
        return self.slave_r.fileno()
    # when the event loop detects an event for us, this means
    # the slave proces wrote something on its output
    # we just have to copy this to the user socket
    def handle_event(self, ts):
        return read_and_copy(
                self.slave_reader, self.sock_file)
    def close(self):
        # note: if we close, we want the other listener
        # (ParallelProcessSocketListener) to close too.
        # that's why we kept a reference to sock_file_r
        # and slave_w, closing them should achieve what
        # we want.
        self.sock_file.close()
        self.slave_r.close()
        self.slave_w.close()

class ParallelProcessSocketListener(object):
    def __init__(self, ev_loop, sock_file, **kwargs):
        self.ev_loop = ev_loop
        self.params = None
        self.sock_file = sock_file
        # provide read_available() method on the socket
        self.sock_reader = SmartBufferingFileReader(self.sock_file)
        self.slave_r = None
        self.slave_w = None
        self.sock_file.write('READY\n')
    def update_params(self):
        pass  # override in subclasses if needed
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
                fcntl.ioctl(sys.stdout.fileno(), termios.TIOCSWINSZ,
                                self.params['win_size'])
            os.execvpe(cmd_args[0], cmd_args, env)
        # the parent should communicate.
        # use unbuffered communication with the slave process
        self.slave_r = os.fdopen(os.dup(fd_slave), 'r', 0)
        self.slave_w = os.fdopen(os.dup(fd_slave), 'w', 0)
        # create a new listener on the event loop for reading
        # what the slave process outputs
        process_listener = ForkPtyProcessListener(
                    self.slave_r, self.slave_w,
                    self.sock_file)
        self.ev_loop.register_listener(process_listener)
    def start_popen(self, cmd_args, env):
        # For efficiency, we let the popen object read directly from the socket.
        # Thus the ev_loop should not longer detect input data on this socket,
        # it should only detect errors, that is why we call update_listener() below.
        self.popen = Popen(cmd_args, env=env, bufsize=1024*1024,
                        stdin=self.sock_file, stdout=self.sock_file, stderr=STDOUT)
        self.ev_loop.update_listener(self, 0)
        self.popen_set_finalize_callback()
    # when the popen object exits, close its output in order
    # to notify the end of transmission to the client.
    def popen_set_finalize_callback(self):
        def monitor_popen(popen, sock_file):
            popen.wait()
            sock_file.close()
            return
        self.popen.monitor_thread = threading.Thread(
                                target=monitor_popen,
                                args=(self.popen,self.sock_file))
        self.popen.monitor_thread.start()
    # let the event loop know what we are reading on
    def fileno(self):
        if self.sock_file.closed:
            return None
        return self.sock_file.fileno()
    # handle_event() will be called when the event loop detects
    # new input data for us.
    def handle_event(self, ts):
        if self.params == None:
            # we did not get the parameters yet, let's do it
            self.params = read_pickle(self.sock_file)
            if self.params == None:
                self.close()    # issue
                return
            self.update_params()
            self.params['cmd'] = self.get_command(**self.params)
            # we now have all info to start the child process
            self.start()
        else:
            # otherwise we are all set. Thus, getting input data means
            # the user wrote something on the prompt (i.e. the socket)
            # we just have to copy this to the slave process input
            return read_and_copy(
                self.sock_reader, self.slave_w)
    def close(self):
        self.sock_file.close()
        if self.slave_r:
            self.slave_r.close()
        if self.slave_w:
            self.slave_w.close()

