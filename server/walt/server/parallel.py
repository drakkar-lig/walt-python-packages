#!/usr/bin/env python
import os, pty, shlex, uuid, fcntl, termios, sys
from subprocess import Popen, PIPE, STDOUT
from walt.common.io import SmartBufferingFileReader, \
                            unbuffered, read_and_copy
from walt.common.tcp import Requests, read_pickle

class ParallelProcessListener(object):
    def __init__(self, slave_r, slave_w, sock_file_r, sock_file_w):
        self.slave_r = slave_r
        self.slave_w = slave_w
        self.sock_file_r = sock_file_r
        self.sock_file_w = sock_file_w
        self.slave_reader = SmartBufferingFileReader(slave_r)
    # let the event loop know what we are reading on
    def fileno(self):
        return self.slave_r.fileno()
    # when the event loop detects an event for us, this means
    # the slave proces wrote something on its output
    # we just have to copy this to the user socket
    def handle_event(self, ts):
        return read_and_copy(
                self.slave_reader, self.sock_file_w)
    def close(self):
        # note: if we close, we want the other listener
        # (ParallelProcessSocketListener) to close too.
        # that's why we kept a reference to sock_file_r
        # and slave_w, closing them should achieve what
        # we want.
        self.sock_file_r.close()
        self.sock_file_w.close()
        self.slave_r.close()
        self.slave_w.close()

class ParallelProcessSocketListener(object):
    def __init__(self, ev_loop, sock_file, **kwargs):
        self.ev_loop = ev_loop
        self.params = None
        # use unbuffered reading & writing on the socket
        self.sock_file_r = unbuffered(sock_file, 'r')
        self.sock_file_w = unbuffered(sock_file, 'w')
        self.slave_r = None
        self.slave_w = None
        self.sock_file_w.write('READY\n')
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
        if 'pty' in self.params and self.params['pty']:
            self.slave_r, self.slave_w = self.start_pty(cmd_args, env)
        else:
            self.slave_r, self.slave_w = self.start_popen(cmd_args, env)
        # provide read_available() method on the socket
        self.sock_reader = SmartBufferingFileReader(self.sock_file_r)
        # create a new listener on the event loop for reading
        # what the slave process outputs
        process_listener = ParallelProcessListener(
                    self.slave_r, self.slave_w,
                    self.sock_file_r, self.sock_file_w)
        self.ev_loop.register_listener(process_listener)
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
        slave_r = os.fdopen(os.dup(fd_slave), 'r', 0)
        slave_w = os.fdopen(os.dup(fd_slave), 'w', 0)
        return slave_r, slave_w
    def start_popen(self, cmd_args, env):
        popen = Popen(cmd_args, env=env,
                        stdin=PIPE, stdout=PIPE, stderr=STDOUT)
        return popen.stdout, popen.stdin
    # let the event loop know what we are reading on
    def fileno(self):
        if self.sock_file_r.closed:
            return None
        return self.sock_file_r.fileno()
    # handle_event() will be called when the event loop detects
    # new input data for us.
    def handle_event(self, ts):
        if self.params == None:
            # we did not get the parameters yet, let's do it
            self.params = read_pickle(self.sock_file_r)
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
        self.sock_file_r.close()
        self.sock_file_w.close()
        if self.slave_r:
            self.slave_r.close()
        if self.slave_w:
            self.slave_w.close()

