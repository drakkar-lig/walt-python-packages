"""walt-server-syncd: standalone WalT clock synchronization daemon.

This daemon implements the server side of the boot-time clock
synchronization protocol used by walt nodes (see walt-clock-sync on
node side). It used to be handled by the main walt-server-daemon
process, but it was moved to its own standalone service so that its
timing accuracy is not affected by the load of other tasks handled by
the main daemon.

The high-level initialization (creating and binding the listening TCP
socket) is done here in python, for easier integration with the rest
of the code base (packaging, systemd notify, etc.), while the actual
event loop -- accepting connections and answering each of them at the
right time -- is implemented in C (see walt/server/ext/clock.c), for
efficiency and timing precision.
"""

import socket

from walt.common.constants import WALT_SERVER_SYNCD_PORT
from walt.common.tcp import set_sock_reuseaddr
from walt.server.ext._c_ext.lib import _clock_syncd_main_loop
from walt.server.tools import notify_systemd

LISTEN_BACKLOG = 256


def run():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    set_sock_reuseaddr(s)
    s.bind(("", WALT_SERVER_SYNCD_PORT))
    s.listen(LISTEN_BACKLOG)
    # notify systemd that we are ready to accept connections
    notify_systemd()
    try:
        _clock_syncd_main_loop(s.fileno())
    except KeyboardInterrupt:
        print()
        print("Aborted.")
    finally:
        s.close()


if __name__ == "__main__":
    run()
