#!/usr/bin/env python3
import fcntl
import os
import pty
import re
import select
import shlex
import struct
import sys
import termios
import time

TTY_ROWS = 50
TTY_COLS = 190

buf = b""
t0 = time.time()


def set_tty_size():
    packed = struct.pack("HHHH", TTY_ROWS, TTY_COLS, 0, 0)
    fcntl.ioctl(1, termios.TIOCSWINSZ, packed)


def ts_print(s):
    now = time.time()
    print(f"{now-t0:.02f}: {s}")


def expect(cond, timeout=5):
    global buf
    deadline = time.time() + timeout
    while not cond():
        now = time.time()
        ts_print("select()")
        r, w, e = select.select([fd_slave], [], [], deadline - now)
        if len(r) == 0:
            print()
            ts_print(f"buf value is:\n{repr(buf)}\n")
            raise Exception("Reached a timeout!")
        chunk = os.read(fd_slave, 256)
        ts_print(f"got {repr(chunk)}")
        buf += chunk
        # ignore bell chars
        buf = re.sub(b"\x07", b"", buf)


def pass_up_to_chars(chars):
    global buf
    # note: .* cannot match a multiline pattern by itself,
    # that's why we use a more complex one.
    buf = re.sub(b"^(.*\n)*.*" + chars, b"", buf, count=1)


def pass_whitespace():
    global buf
    buf = buf.lstrip()


def flush_buf():
    global buf
    buf = b""


def flush_read():
    r, w, e = select.select([fd_slave], [], [], 0)
    if len(r) > 0:
        os.read(fd_slave, 1024)


def send(chars):
    os.write(fd_slave, chars)
    ts_print(f"sent {repr(chars)}")


def expect_and_pass_prompt():
    expect(lambda: b"# " in buf)
    pass_up_to_chars(b"# ")


def slave_reinit_autocomplete():
    send(b"complete -r\r")
    expect_and_pass_prompt()
    send(b"walt advanced dump-bash-autocomplete > /tmp/auto.sh\r")
    expect_and_pass_prompt()
    send(b". /tmp/auto.sh\r")
    expect_and_pass_prompt()


def test_complete(cmd, expected, num_tabs):
    if num_tabs == 1:
        tabs = b"\t"
    elif num_tabs == 2:
        tabs = b"\t\t"
    # send command and tab or tab-tab
    send(cmd + tabs)
    # typed command is echo-ed
    expect(lambda: cmd in buf)
    pass_up_to_chars(cmd)
    # if tab-tab, then completions are output on a new line
    if num_tabs == 2:
        expect(lambda: b"\r" in buf)
        pass_whitespace()
    # check if we get the expected completion within 10s
    # (or an unexpected one, or a timeout)
    expect(lambda: expected in buf)
    print("completed OK.")
    # clear the current line (ctrl-e ctrl-u)
    send(b"\x05\x15")
    time.sleep(0.5)
    flush_buf()
    flush_read()


# startup
slave_pid, fd_slave = pty.fork()

if slave_pid == 0:
    # tab tab completions may wrap up if terminal width is too small
    set_tty_size()
    os.execvp("bash", shlex.split("bash --norc -i -l"))

expect_and_pass_prompt()
slave_reinit_autocomplete()
instructions = sys.stdin.read()
for line in instructions.splitlines():
    inst, cmd, expected = shlex.split(line)
    cmd = cmd.encode("ascii")
    expected = expected.encode("ascii")
    num_tabs = {"test_tab_complete": 1, "test_tabtab_complete": 2}[inst]
    print(f"** Auto-completion of {repr(cmd)}...")
    test_complete(cmd, expected, num_tabs)
