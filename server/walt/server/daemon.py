#!/usr/bin/env python
import os
import signal

from walt.common.tools import interrupt_print
from walt.server.process import EvProcessesManager
from walt.server.processes.blocking.process import ServerBlockingProcess
from walt.server.processes.db.process import ServerDBProcess
from walt.server.processes.hub.process import ServerHubProcess
from walt.server.processes.main.process import ServerMainProcess
from walt.server.spec import reload_server_spec
from walt.server.tools import fix_pdb, set_rlimits


def on_sighup_reload_conf():
    def signal_handler(signal, frame):
        interrupt_print("SIGHUP received. Reloading conf.")
        reload_server_spec()

    signal.signal(signal.SIGHUP, signal_handler)


def on_sigchld_call_waitpid():
    def signal_handler(sig, frame):
        while True:
            try:
                waitstatus = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            pid = waitstatus[0]
            if pid > 0:
                # import pdb; pdb.set_trace()
                # interrupt_print(f'process pid={pid} has stopped.')
                continue
            else:
                return

    signal.signal(signal.SIGCHLD, signal_handler)


def block_signals():
    # these signals should only be able to interrupt us at chosen times
    # (cf. event loop)
    signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGHUP, signal.SIGCHLD])


def run():
    # fix pdb when running in a subprocess
    fix_pdb()
    # set appropriate OS resource limits
    set_rlimits()
    # handle signals
    on_sighup_reload_conf()
    on_sigchld_call_waitpid()
    block_signals()
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
