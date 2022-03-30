#!/usr/bin/env python
import signal
from walt.server.tools import set_rlimits, fix_pdb
from walt.common.process import EvProcessesManager
from walt.server.processes.main.process import ServerMainProcess
from walt.server.processes.blocking.process import ServerBlockingProcess
from walt.server.processes.hub.process import ServerHubProcess
from walt.server.processes.db.process import ServerDBProcess
from walt.server.spec import reload_server_spec

def on_sighup_reload_conf():
    def signal_handler(signal, frame):
        print('SIGHUP received. Reloading conf.')
        reload_server_spec()
    signal.signal(signal.SIGHUP, signal_handler)

def run():
    # fix pdb when running in a subprocess
    fix_pdb()
    # set appropriate OS resource limits
    set_rlimits()
    # on SIGHUP, reload server.spec
    on_sighup_reload_conf()
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
    tman.start()

if __name__ == "__main__":
    run()

