#!/usr/bin/env python

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

