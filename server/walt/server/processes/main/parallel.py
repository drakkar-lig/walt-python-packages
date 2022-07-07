#!/usr/bin/env python
import os, pty, shlex, fcntl, termios, sys, socket, signal, pickle
from subprocess import Popen, STDOUT
from walt.common.io import read_and_copy
from walt.common.tcp import read_pickle
from walt.common.tty import set_tty_size_raw, set_tty_size

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
        return read_and_copy(
                self.env.slave_r, self.env.client_sock_file)
    def end_child(self):
        try:
            os.kill(self.slave_pid, signal.SIGKILL)
        except OSError:
            pass
        os.waitpid(self.slave_pid, 0)   # wait for child's end
    def close(self):
        self.end_child()
        self.env.close()

class ParallelProcessSocketListener(object):
    def __init__(self, ev_loop, sock_file, **kwargs):
        self.ev_loop = ev_loop
        self.params = None
        self.client_sock_file = sock_file
        self.slave_r, self.slave_w = None, None
        self.monitor_r = None
        self.popen = None
        self.send_client('READY\n')
    def send_client(self, s):
        self.client_sock_file.write(s.encode('UTF-8'))
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
        if 'tty_mode' in self.params and self.params['tty_mode'] is True:
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
        self.slave_r = os.fdopen(os.dup(fd_slave), 'rb', 0)
        self.slave_w = os.fdopen(fd_slave, 'wb', 0)
        # create a new listener on the event loop for reading
        # what the slave process outputs
        process_listener = ForkPtyProcessListener(slave_pid, self)
        self.ev_loop.register_listener(process_listener)
    def start_popen(self, cmd_args, env):
        # For efficiency, we let the popen object read & write directly on the socket.
        # Thus the ev_loop should just detect when the popen process ends.
        # In order to achieve this we create a pipe and let the child inherit only
        # one of the ends. By letting the event loop monitor the other end, we can
        # detect when the popen process ends.
        self.monitor_r, monitor_w = os.pipe()
        os.set_inheritable(self.monitor_r, False)
        os.set_inheritable(monitor_w, True)
        self.popen = Popen(cmd_args, env=env, bufsize=1024*1024,
                        stdin=self.client_sock_file, stdout=self.client_sock_file, stderr=STDOUT,
                        pass_fds=(self.client_sock_file.fileno(), monitor_w))
        os.close(monitor_w)   # this should only be kept open in the popen child, not here
        # we should now listen on self.monitor_r
        self.ev_loop.update_listener(self)
    # let the event loop know what we are reading on
    def fileno(self):
        if self.monitor_r is None:
            if self.client_sock_file.closed:
                return None
            return self.client_sock_file.fileno()
        else:
            return self.monitor_r
    # handle_event() will be called when the event loop detects
    # new input data for us.
    def handle_event(self, ts):
        if self.params == None:
            # we did not get the parameters yet, let's do it
            self.params = read_pickle(self.client_sock_file)
            if self.params == None:
                return False    # issue, this will call self.close()
            self.update_params()
            if self.prepare(**self.params) == False:
                return False    # issue, this will call self.close()
            self.params['cmd'] = self.get_command(**self.params)
            # we now have all info to start the child process
            self.start()
        else:
            # otherwise we are all set. Getting here means
            # we got input data or the child process ended.
            if self.monitor_r is None:
                # tty mode --
                # in this mode input data and window resize events are
                # multiplexed on the socket.
                try:
                    evt_info = pickle.load(self.client_sock_file)
                    if evt_info['evt'] == 'input_data':
                        self.slave_w.write(evt_info['data'])
                        self.slave_w.flush()
                    elif evt_info['evt'] == 'window_resize':
                        win_size = (evt_info['lines'], evt_info['columns'])
                        set_tty_size(self.slave_w.fileno(), win_size)
                except Exception as e:
                    print(self, e)
                    return False    # issue, this will call self.close()
            else:
                # popen mode --
                # in this mode the child process reads raw data directly on
                # the socket, and we are just monitoring self.monitor_r, thus
                # getting here means our child popen process closed its end
                # of the pipe (monitor_w) which probably means it ended.
                return False # this will call self.close()
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
        if self.popen:
            self.popen.wait()
            self.popen = None
        if self.monitor_r:
            os.close(self.monitor_r)
            self.monitor_r = None
