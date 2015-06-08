#!/usr/bin/env python
import rpyc, pexpect
from walt.common.io import SmartBufferingFileReader, unbuffered

# The Prompt class allows to manage interactive command
# prompts in the context of the event loop.
class Prompt(object):
    def __init__(self, cmd, out_stream, ev_loop):
        self.cmd = cmd
        self.out_stream = out_stream
        self.ev_loop = ev_loop
        self.child = None
    def start(self):
        self.child = pexpect.spawn(self.cmd)
        self.child.setecho(False)
        self.in_file = SmartBufferingFileReader(unbuffered(self.child, 'r'))
        self.child_input = unbuffered(self.child, 'w')
        self.ev_loop.register_listener(self)
    def write(self, s):
        self.child_input.write(s)
    def flush(self):
        self.child.flush()
    def fileno(self):
        return self.child.fileno()
    def handle_event(self):
        s = self.in_file.read_available()
        if s == '':
            return False    # leave the event loop
        self.out_stream.write(s)
        self.out_stream.flush()
    def is_valid(self):
        # check the child process
        return self.child.isalive()
    def close(self):
        if self.child.isalive():
            self.child.terminate(force=True)

# The RemotePrompt class allows to expose a Prompt object
# through a RPyC connection (in order to let the client
# interact with it).
class RemotePrompt(Prompt):
    def __init__(self, cmd, rpyc_conn, ev_loop, client_handler):
        Prompt.__init__(self, cmd, client_handler, ev_loop)
        # expose write() and flush() to RPyC remote users
        self.exposed_write = self.write
        self.exposed_flush = self.flush
        self.conn = rpyc_conn
        self.client_handler = client_handler

    def conn_is_valid(self):
        try:
            if self.conn.closed:
                return False
        except ReferenceError:
            return False
        return True

    # a valid RemotePrompt is a valid Prompt
    # with a valid connection
    def is_valid(self):
        if not self.conn_is_valid():
            return False
        # call base class method
        return Prompt.is_valid(self)

    def close(self):
        # warn client if it is still there
        if self.conn_is_valid():
            # the client will disconnect and we will lose
            # the rpyc connection, so just send and forget
            async_stop = rpyc.async(self.client_handler.stop)
            async_stop()
        # call base class method
        Prompt.close(self)

