import os
import re
import socket
import sys
from select import select

from walt.client.log import LogsFlowFromServer
from walt.common.term import TTYSettings, clear_screen

WELCOME_MESSAGE = """
This will connect to the virtual node console. You can use <ctrl-a> <d> to quit.
See 'walt help show node-console' for more info.

Type <enter> to validate, or <ctrl-c> to abort: """


def console_loop(server, conn, node_info):
    re_escape_filter = re.compile(r"\x1b(c|\[2J)".encode("ascii"))
    conn_fd = conn.fileno()
    esc_sequence = False

    # we will wait on 2 file descriptors
    fds = [0, conn_fd]

    while True:
        rlist, wlist, elist = select(fds, [], fds)
        if len(elist) > 0 and len(rlist) == 0:
            break
        fd = rlist[0]
        if fd == conn_fd:
            record = conn.read_log_record()
            if record is None:
                break
            chunk = eval(record["line"])
            chunk = re_escape_filter.sub(b"", chunk)
            os.write(1, chunk)
        else:  # stdin
            try:
                buf = os.read(0, 4096)
                if buf == b"":  # stdin closed
                    break
                desc_buf = (esc_sequence, buf)
                # <ctrl-a>: start escape sequence
                if desc_buf == (False, b"\x01"):
                    esc_sequence = True
                    continue
                # <ctrl-a> <a> or <ctrl-a> <ctrl-a>: send <ctrl-a>
                elif desc_buf == (True, b"a") or desc_buf == (True, b"\x01"):
                    buf = b"\x01"
                    esc_sequence = False
                # <ctrl-a> <d>: disconnect
                elif desc_buf == (True, b"d"):
                    break
                # <ctrl-a> <other-key>: unknown shortcut, ignore
                elif esc_sequence is True:
                    esc_sequence = False
                    continue
                server.vnode_console_input(node_info["mac"], buf)
                # os.write(1, (repr(buf) + '\r\n').encode('ascii'))
            except socket.error:
                break


def run_node_console(server, node_info):
    # establish logs connection to server
    conn = LogsFlowFromServer()
    conn.request_log_dump(
        history=None,
        realtime=True,
        issuers=(node_info["name"],),
        streams="virtualconsole",
        logline_regexp=None,
    )

    # run loop, with or without TTY handling
    if sys.stdout.isatty() and sys.stdin.isatty():
        # on a TTY
        print(WELCOME_MESSAGE, end="")
        sys.stdout.flush()
        input()
        print("OK, connecting.")
        tty_settings = TTYSettings()
        try:
            clear_screen()
            sys.stdout.flush()
            tty_settings.set_raw_no_echo()
            console_loop(server, conn, node_info)
        finally:
            tty_settings.restore()
            print("\x1bc")  # full terminal reset
            print("Disconnected from console.")
    else:
        console_loop(server, conn, node_info)
