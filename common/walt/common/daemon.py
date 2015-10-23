#!/usr/bin/env python

import sys, logging, signal
from plumbum import cli
from rpyc.utils.server import Server
from rpyc.core import SocketStream, Channel, Connection
from evloop import EventLoop

# This class is designed to manage 1 RPyC client
# connexion, and integrate our event loop 
# mechanism. 
class RPyCClientManager(object):
    def __init__(self, conn):
        self.conn = conn

    def start(self):
        self.conn._init_service()

    def fileno(self):
        return self.conn.fileno()

    def handle_event(self, ts):
        try:
            self.conn.serve()
        except:
            return False    # leave the event loop

    def close(self):
        self.conn.close()

# We define a subclass of rpyc.utils.server.Server 
# that integrates with our event loop.
# This allows to avoid thread concurrency handling.
# As a side effect we will process only one RPyC 
# request at a time, so we should avoid lengthy 
# processing when answering a client. 
class RPyCServer(Server):
    """Mono-thread RPyC Server."""
    # we will use this instead of the start() method
    # in order to be able to manage the loop and catch
    # exceptions in the calling code.
    def prepare(self, ev_loop):
        self.ev_loop = ev_loop
        self.listener.listen(self.backlog)
        self.active = True
        self.logger.info("server started on [%s]:%s.", self.host, self.port)

    def end(self):
        self.close()
        self.logger.info("server has terminated.")

    # define what we will do with our new client
    def _accept_method(self, sock):
        config = dict(
                self.protocol_config,
                credentials = None,
                endpoints = (sock.getsockname(), sock.getpeername()),
                logger = self.logger)
        conn = Connection(
                self.service,
                Channel(SocketStream(sock)),
                config = config,
                _lazy = True)
        manager = RPyCClientManager(conn)
        manager.start()
        self.ev_loop.register_listener(manager)

    # the event loop needs to know which file descriptor
    # we are waiting on
    def fileno(self):
        return self.listener.fileno()

    # the event loop will call this when there is a new request
    # for us (i.e. an RPyC client connection)
    def handle_event(self, ts):
        self.accept()

def exit_handler(_signo, _stack_frame):
    # Raises SystemExit(0):
    sys.exit(0)

class WalTDaemon(cli.Application):
    """Skeleton for a RPyC daemon application."""
    str_log_level = cli.SwitchAttr("--log", str, default = "WARNING",
                help = "Specify the log-level")

    def set_log_level(self):
        """Sets the log-level of the logger"""
        numeric_level = getattr(logging, self.str_log_level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % self.str_log_level)
        else:
            logging.basicConfig(level=numeric_level)

    def main(self):
        self.do_main(**self.getParameters())

    def do_main(self, ev_loop, service_cl, port):
        self.set_log_level()
        self.set_signal_handlers()
        self.init()
        rpyc_server = RPyCServer(
                        service_cl, port = port)
        ev_loop.register_listener(rpyc_server)
        self.init_end()
        try:
            rpyc_server.prepare(ev_loop)
            ev_loop.loop()
        except KeyboardInterrupt:
            sys.stderr.write('Interrupted.\n')
            sys.stderr.flush()
            rpyc_server.end()

    def set_signal_handlers(self):
        signal.signal(signal.SIGTERM, exit_handler)

    # overwrite in subclass if needed
    def init(self):
        pass

    def init_end(self):
        pass
