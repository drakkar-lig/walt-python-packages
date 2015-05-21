#!/usr/bin/env python

import sys, logging, signal
from plumbum import cli
from rpyc.utils.server import Server
from eventloop import EventLoop

# We define a simple subclass of rpyc.utils.server.Server 
# that runs a loop in a mono-thread way.
# This allows to avoid thread concurrency handling.
# As a side effect we will process only one client
# request at a time. 
# This is a preliminary implementation that could be 
# improved if the need arises.
# We also want to pass any exception to the calling code.
class SimpleRPyCServer(Server):
    """Mono-thread RPyC Server."""
    # we will use this instead of the start() method
    # in order to be able to manage the loop and catch
    # exceptions in the calling code.
    def prepare(self):
        self.listener.listen(self.backlog)
        self.active = True
        self.logger.info("server started on [%s]:%s.", self.host, self.port)

    def end(self):
        self.close()
        self.logger.info("server has terminated.")

    # any subclass of Server should define this.
    # we just do what's expected.
    def _accept_method(self, sock):
        self._authenticate_and_serve_client(sock)

    # the event loop needs to know which file descriptor
    # we are waiting on
    def fileno(self):
        return self.listener.fileno()

    # the event loop will call this when there is a new request
    # for us (i.e. an RPyC client connection)
    def handle_event(self):
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

    def info_message(self, msg):
        sys.stdout.write(msg)
        sys.stdout.flush()

    def main(self):
        self.info_message("Initializing... ")
        self.set_log_level()
        self.set_signal_handlers()
        service_cl, port = self.getRPyCServiceClassAndPort()
        self.ev_loop = EventLoop()
        self.rpyc_server = SimpleRPyCServer(
                        service_cl, port = port)
        self.ev_loop.register_listener(self.rpyc_server)
        self.init()
        self.info_message("Done.\n")  # end of initialization
        try:
            self.rpyc_server.prepare()
            self.ev_loop.loop()
        except KeyboardInterrupt:
            self.info_message('Interrupted.\n')
            self.rpyc_server.end()

    def set_signal_handlers(self):
        signal.signal(signal.SIGTERM, exit_handler)

    # overwrite in subclass if needed
    def init(self):
        pass

