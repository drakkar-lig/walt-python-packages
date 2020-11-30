#!/usr/bin/env python
import signal
from walt.common.tools import on_sigterm_throw_exception
from walt.server.tools import set_rlimits
from walt.common.thread import EvThreadsManager
from walt.server.threads.main.thread import ServerMainThread
from walt.server.threads.blocking.thread import ServerBlockingThread
from walt.server.threads.hub.thread import ServerHubThread
from walt.server.spec import reload_server_spec

def on_sighup_reload_conf():
    def signal_handler(signal, frame):
        print('SIGHUP received. Reloading conf.')
        reload_server_spec()
    signal.signal(signal.SIGHUP, signal_handler)

def run():
    # set appropriate OS resource limits
    set_rlimits()
    # exit gracefully on SIGTERM, reload conf on SIGHUP
    on_sigterm_throw_exception()
    on_sighup_reload_conf()
    # create the thread manager
    tman = EvThreadsManager()
    # create main thread
    main_thread = ServerMainThread(tman)
    # create blocking thread
    blocking_thread = ServerBlockingThread(tman, main_thread.server)
    # create hub thread
    hub_thread = ServerHubThread(tman)
    # connect them
    main_thread.blocking.connect(blocking_thread.main)
    main_thread.hub.connect(hub_thread.main)
    # start!
    tman.start()

if __name__ == "__main__":
    run()

