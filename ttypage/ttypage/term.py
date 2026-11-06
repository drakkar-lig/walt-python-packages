"""Terminal helpers used by the pager.

This is a subset of walt.common.term (WalT project), copied here so that
ttypage does not depend on WalT packages.
"""
import array
import curses
import fcntl
import sys
import termios
import tty
from contextlib import contextmanager

ESC_CLEAR = b"\x1b[2J\x1b[H"


def _get_win_size():
    buf = array.array("h", [0, 0, 0, 0])
    fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, buf, True)
    return buf


class TTYSettings(object):
    def __init__(self):
        self.tty_fd = sys.stdout.fileno()
        # save
        self.saved = termios.tcgetattr(self.tty_fd)
        curses.setupterm()
        self.num_colors = curses.tigetnum("colors")

    def set_raw_no_echo(self):
        # set raw mode
        tty.setraw(self.tty_fd, termios.TCSADRAIN)
        # disable echo
        new = termios.tcgetattr(self.tty_fd)
        new[3] &= ~termios.ECHO
        termios.tcsetattr(self.tty_fd, termios.TCSADRAIN, new)

    def restore(self):
        # return saved conf
        termios.tcsetattr(self.tty_fd, termios.TCSADRAIN, self.saved)

    @property
    def win_size(self):
        return _get_win_size()

    @property
    def rows(self):
        return self.win_size[0]

    @property
    def cols(self):
        return self.win_size[1]

    def get_win_size(self):
        return self.win_size

    def set_title(self, title):
        import os
        os.write(self.tty_fd, f"\x1b]0;{title}\007".encode())


def  _run_get_stdout(cmd):
    from subprocess import run, PIPE
    return run(cmd, stdout=PIPE, stderr=PIPE, shell=True).stdout



@contextmanager
def alternate_screen_buffer(mouse_wheel_as_arrow_keys=False):
    escape_enter = _run_get_stdout("tput smcup")
    escape_exit = _run_get_stdout("tput rmcup")
    if escape_enter == b'' or escape_exit == b'':
        # the terminal does not support this, just clear
        escape_enter = ESC_CLEAR
        escape_exit = ESC_CLEAR
    else:
        # the terminal probably also supports alternate scroll mode
        # (i.e., scroll using the mouse wheel; unfortunately there is
        # no tput property to check this).
        if mouse_wheel_as_arrow_keys:
            escape_enter = escape_enter + b"\x1b[?1007h"
            escape_exit = b"\x1b[?1007l" + escape_exit
    # ok let's go
    sys.stdout.buffer.write(escape_enter)
    sys.stdout.flush()
    yield
    sys.stdout.buffer.write(escape_exit)
    sys.stdout.flush()


def clear_screen():
    sys.stdout.buffer.write(ESC_CLEAR)
    sys.stdout.flush()


@contextmanager
def on_sigwinch_call(handler):
    from signal import signal, SIGWINCH
    prev_on_sigwinch = signal(SIGWINCH, handler)
    try:
        yield
    finally:
        signal(SIGWINCH, prev_on_sigwinch)


class SIGWINCHException(Exception):
    pass


def _on_sigwinch_raise_exception(sig, frame):
    raise SIGWINCHException()


@contextmanager
def on_sigwinch_raise_exception():
    with on_sigwinch_call(_on_sigwinch_raise_exception):
        yield


def _on_sigwinch_interrupt_pause(sig, frame):
    pass  # nothing more to do


@contextmanager
def on_sigwinch_interrupt_pause():
    with on_sigwinch_call(_on_sigwinch_interrupt_pause):
        yield


def wait_for_large_enough_terminal(min_width):
    width = _get_win_size()[1]
    if width >= min_width:
        return False    # no resizing needed
    clear_screen()
    print()
    print("The terminal window is too small for displaying next screen.",
          end="\r\n")
    print("Please resize it now.", end="\r\n")
    from signal import pause
    import time
    with on_sigwinch_interrupt_pause():
        while True:
            width = _get_win_size()[1]
            print(f"\rCurrent size: {width}    ", end="")
            sys.stdout.flush()
            if width >= min_width:
                print("\r\n\nOK, continuing.\r\n\n", end="")
                time.sleep(1.5)
                break
            pause()  # wait for next signal
    return True
