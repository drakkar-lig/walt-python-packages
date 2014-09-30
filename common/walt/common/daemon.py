#!/usr/bin/env python

import sys, logging
from plumbum import cli
from rpyc.utils.server import Server

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

    # we redefine the start() method in order to be able to catch 
    # exceptions in the calling code.
    def start(self):
        self.listener.listen(self.backlog)
        self.active = True
        self.logger.info("server started on [%s]:%s.", self.host, self.port)
        while self.active:
            self.accept()
            self.logger.info("request served.")
        self.close()
        self.logger.info("server has terminated.")

    # any subclass of Server should define this.
    # we just do what's expected.
    def _accept_method(self, sock):
        self._authenticate_and_serve_client(sock)


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
        sys.stdout.write("Initializing... ")
        sys.stdout.flush()
        self.set_log_level()
        service_cl, port = self.getRPyCServiceClassAndPort()
        self.init()
        server = SimpleRPyCServer(service_cl, port = port)
        print("Done.")  # end of initialization
        try:
            server.start()
        except KeyboardInterrupt:
            print 'Interrupted.'

    # overwrite in subclass if needed
    def init(self):
        pass 

