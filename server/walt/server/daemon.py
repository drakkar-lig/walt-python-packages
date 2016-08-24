#!/usr/bin/env python

from walt.common.thread import EvThreadsManager
from walt.server.thread.main.thread import ServerMainThread

def run():
    tman = EvThreadsManager()
    # create main thread
    ServerMainThread(tman)
    # start!
    tman.start()

if __name__ == "__main__":
    run()

