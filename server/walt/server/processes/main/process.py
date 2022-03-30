import os
from walt.common.process import EvProcess
from walt.server.processes.main.server import Server
from walt.server.processes.main.hub import HubRPCProcessConnector

class ServerMainProcess(EvProcess):
    def __init__(self, tman, level):
        EvProcess.__init__(self, tman, 'server-main', level)
        self.server = Server(self.ev_loop)
        self.db = self.server.db
        self.blocking = self.server.blocking
        self.hub = HubRPCProcessConnector(self.server)

    def prepare(self):
        self.server.prepare()
        self.register_listener(self.hub)
        self.register_listener(self.blocking)
        self.register_listener(self.db)
        self.notify_systemd()
        self.server.update()
        print('Ready.')

    def notify_systemd(self):
        if 'NOTIFY_SOCKET' in os.environ:
            import sdnotify
            sdnotify.SystemdNotifier().notify("READY=1")
            # note: podman hangs (at least on debian buster) if we
            # do not disable systemd notify mechanism.
            # at this point we no longer need it, so let's discard
            # the env variable.
            del os.environ['NOTIFY_SOCKET']

    def cleanup(self):
        self.server.cleanup()
