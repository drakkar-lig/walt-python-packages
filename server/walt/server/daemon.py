#!/usr/bin/env python

import sys

from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.common.daemon import RPyCServer
from walt.common.service import RPyCService
from walt.common.thread import EvThread, EvThreadsManager
from walt.common.versions import UPLOAD
from walt.server.thread.main.api.cs import CSAPI
from walt.server.thread.main.api.ns import NSAPI
from walt.server.thread.main.network.setup import setup
from walt.server.thread.main.network.tools import set_server_ip
from walt.server.thread.main.server import Server
from walt.server.thread.main.ui.manager import UIManager
from walt.server.tools import AutoCleaner


WALT_SERVER_DAEMON_VERSION = 'server v' + str(UPLOAD)

@RPyCService
class PlatformService(object):
    ALIASES=("WalT_Platform",)

    def __init__(self, server):
        images, devices, nodes, logs = \
            server.images, server.devices, server.nodes, server.logs
        self.cs = CSAPI(WALT_SERVER_DAEMON_VERSION,
                server, images, devices, nodes, logs)
        self.ns = NSAPI(devices, nodes)
        self.exposed_cs = self.cs
        self.exposed_ns = self.ns

    def on_connect(self):
        self.cs.on_connect(self._conn)
        self.ns.on_connect(self._conn)

    def on_disconnect(self):
        self.cs.on_disconnect()
        self.ns.on_disconnect()

class WalTServerDaemon(object):
    """WalT (wireless testbed) server daemon."""
    VERSION = WALT_SERVER_DAEMON_VERSION

    def __init__(self, server):
        self.server, self.ev_loop = server, server.ev_loop

    def run(self):
        rpyc_server = RPyCServer(
                        PlatformService(self.server),
                        port = WALT_SERVER_DAEMON_PORT)
        self.ev_loop.register_listener(rpyc_server)
        self.server.ui.set_status('Ready.')
        try:
            rpyc_server.prepare(self.ev_loop)
            self.ev_loop.loop()
        except KeyboardInterrupt:
            sys.stderr.write('Interrupted.\n')
            sys.stderr.flush()
            rpyc_server.end()

def notify_systemd():
    try:
        import sdnotify
        sdnotify.SystemdNotifier().notify("READY=1")
    except:
        pass

def run():
    ui = UIManager()
    server = Server(ui)
    # set ip on WalT network (eth0.1)
    set_server_ip()
    server.dhcpd.update(force=True)
    setup(ui)
    notify_systemd()
    daemon = WalTServerDaemon(server)
    with AutoCleaner(server):
        server.update()
        daemon.run()

if __name__ == "__main__":
    run()

