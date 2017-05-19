#!/usr/bin/env python
from walt.common.tools import on_sigterm_throw_exception
from walt.common.thread import EvThreadsManager
from walt.server.threads.main.thread import ServerMainThread
from walt.server.threads.blocking.thread import ServerBlockingThread
from walt.server.threads.hub.thread import ServerHubThread

def run():
    # exit gracefully on SIGTERM
    on_sigterm_throw_exception()
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

