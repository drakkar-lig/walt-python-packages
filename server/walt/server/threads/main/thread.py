from walt.common.thread import EvThread
from walt.server.threads.main.network.setup import setup
from walt.server.threads.main.server import Server
from walt.server.threads.main.ui.manager import UIManager
from walt.server.threads.main.hub import HubRPCThreadConnector

class ServerMainThread(EvThread):
    def __init__(self, tman):
        EvThread.__init__(self, tman, 'server-main')
        self.ui = UIManager()
        self.server = Server(self, self.ui)
        self.blocking = self.server.blocking
        self.hub = HubRPCThreadConnector(self.server)

    def prepare(self):
        self.server.prepare()
        self.register_listener(self.hub)
        self.register_listener(self.blocking)
        setup(self.ui)
        self.notify_systemd()
        self.server.ui.set_status('Ready.')
        self.server.update()
    
    def notify_systemd(self):
        try:
            import sdnotify
            sdnotify.SystemdNotifier().notify("READY=1")
        except:
            pass

    def cleanup(self):
        self.server.cleanup()
