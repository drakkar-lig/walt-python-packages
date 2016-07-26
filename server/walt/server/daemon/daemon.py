#!/usr/bin/env python

import rpyc

from walt.server.server import Server
from walt.server.network import setup
from walt.server.network.tools import set_server_ip
from walt.server.tools import AutoCleaner
from walt.server.ui.manager import UIManager
from walt.common.daemon import WalTDaemon
from walt.common.versions import UPLOAD
from walt.common.constants import WALT_SERVER_DAEMON_PORT
from walt.server.daemon.cs import CSAPI
from walt.server.daemon.ns import NSAPI

WALT_SERVER_DAEMON_VERSION = 'server v' + str(UPLOAD)

class PlatformService(rpyc.Service):
    ALIASES=("WalT_Platform",)

    def __init__(self, *args, **kwargs):
        rpyc.Service.__init__(self, *args, **kwargs)
        server = Server.instance
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

class WalTServerDaemon(WalTDaemon):
    """WalT (wireless testbed) server daemon."""
    VERSION = WALT_SERVER_DAEMON_VERSION

    def getParameters(self):
        return dict(
                service_cl = PlatformService,
                port = WALT_SERVER_DAEMON_PORT,
                ev_loop = Server.instance.ev_loop)

    def init_end(self):
        Server.instance.ui.set_status('Ready.')

def notify_systemd():
    try:
        import sdnotify
        sdnotify.SystemdNotifier().notify("READY=1")
    except:
        pass

def run():
    ui = UIManager()
    myserver = Server(ui)
    # set ip on WalT network (eth0.1)
    set_server_ip()
    myserver.dhcpd.update(force=True)
    setup.setup(ui)
    notify_systemd()
    with AutoCleaner(myserver) as Server.instance:
        myserver.update()
        WalTServerDaemon.run()

if __name__ == "__main__":
    run()

