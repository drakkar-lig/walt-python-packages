import signal

from walt.common.tools import interrupt_print
from walt.server.process import EvProcess
from walt.server.process import SyncRPCProcessConnector
from walt.server.processes.main.hub import HubRPCProcessConnector
from walt.server.processes.main.blocking import BlockingTasksManager
from walt.server.spec import reload_server_spec


def on_sighup_reload_conf():
    def signal_handler(signal, frame):
        interrupt_print("SIGHUP received. Reloading conf.")
        reload_server_spec()

    signal.signal(signal.SIGHUP, signal_handler)


class ServerMainProcess(EvProcess):
    def __init__(self, tman, level):
        EvProcess.__init__(self, tman, "server-main", level)
        self.server = None  # not configured yet
        self.db = SyncRPCProcessConnector(label="main-to-db",
                                          serialize_reqs=True)
        tman.attach_file(self, self.db)
        self.blocking = BlockingTasksManager()
        tman.attach_file(self, self.blocking)
        self.hub = HubRPCProcessConnector()
        tman.attach_file(self, self.hub)

    def prepare(self):
        from walt.server.processes.main.server import Server
        on_sighup_reload_conf()
        self.server = Server(self.ev_loop, self.db, self.blocking)
        self.hub.configure(self.server)
        self.ev_loop.register_listener(self.hub)
        self.ev_loop.register_listener(self.blocking)
        self.ev_loop.register_listener(self.db)
        self.server.prepare()
        self.notify_systemd()
        self.server.update()
        print("Ready.")

    def notify_systemd(self):
        import os
        if "NOTIFY_SOCKET" in os.environ:
            import sdnotify

            sdnotify.SystemdNotifier().notify("READY=1")
            # note: podman hangs (at least on debian buster) if we
            # do not disable systemd notify mechanism.
            # at this point we no longer need it, so let's discard
            # the env variable.
            del os.environ["NOTIFY_SOCKET"]

    def cleanup(self):
        if self.server is not None:
            self.server.cleanup()
