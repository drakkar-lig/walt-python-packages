#!/usr/bin/env python
from multiprocessing import set_start_method
from walt.server.process import EvProcessesManager
from walt.server.processes.blocking.process import ServerBlockingProcess
from walt.server.processes.db.process import ServerDBProcess
from walt.server.processes.hub.process import ServerHubProcess
from walt.server.processes.main.process import ServerMainProcess


def run():
    set_start_method('spawn')
    # create the process manager
    tman = EvProcessesManager()
    # create db process
    db_process = ServerDBProcess(tman, level=1)
    # create main process
    main_process = ServerMainProcess(tman, level=2)
    # create blocking process
    blocking_process = ServerBlockingProcess(tman, level=3)
    # create hub process
    hub_process = ServerHubProcess(tman, level=3)
    # connect them
    main_process.blocking.connect(blocking_process.main)
    main_process.hub.connect(hub_process.main)
    main_process.db.connect(db_process.main)
    blocking_process.db.connect(db_process.blocking)
    # start!
    try:
        tman.start()
    except KeyboardInterrupt:
        print("Interrupted.")


if __name__ == "__main__":
    run()
