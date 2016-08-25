#!/usr/bin/env python

from walt.common.thread import EvThreadsManager
from walt.server.threads.main.thread import ServerMainThread
from walt.server.threads.blocking.thread import ServerBlockingThread

class Shared(object):
    pass

def run():
    # initialize shared context
    shared = Shared()
    shared.tasks = {}
    # create the thread manager
    tman = EvThreadsManager()
    # create main thread
    main_thread = ServerMainThread(tman, shared)
    # create blocking thread
    blocking_thread = ServerBlockingThread(tman, shared)
    # connect them
    main_thread.blocking.connect(blocking_thread.main)
    # start!
    tman.start()

if __name__ == "__main__":
    run()

