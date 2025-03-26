#!/usr/bin/env python
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


NORMAL = "\x1b[0m"
INVERSE = "\x1b[7m"
CURSOR_VISIBLE = "\x1b[?25h"
CURSOR_HIDDEN = "\x1b[?25l"
CURSOR_UP_N_ROWS = "\x1b[%dA"
CURSOR_DOWN_N_ROWS = "\x1b[%dB"


def choose(prompt, options, allow_ctrl_c=False):
    # options can be a dict where keys are descriptions of options
    # and values indicating the corresponding value to return.
    # otherwise, it can be a simple list or tuple and the selected
    # item will be returned.
    if isinstance(options, dict):
        options_desc, options_values = tuple(zip(*options.items()))
    else:
        options_desc, options_values = options, None
    print(prompt)
    tty = TTYSettings()
    selected = 0
    # wheck if we should print in row for compactness
    # (only do that when options are single words (no space) and
    # the terminal row is large enough)
    single_row_length = sum((len(v) + 2) for v in options_desc) + 1
    single_row_mode = (single_row_length <= tty.cols) and not any(
        " " in opt for opt in options_desc
    )
    try:
        tty.set_raw_no_echo()
        sys.stdout.write(CURSOR_HIDDEN)
        while True:
            formatted_values = []
            for i, v in enumerate(options_desc):
                if i == selected:
                    v = INVERSE + v + NORMAL
                v = "  " + v
                if not single_row_mode:
                    if i == selected:
                        v = ">" + v + "\r\n"
                    else:
                        v = " " + v + "\r\n"
                formatted_values.append(v)
            if single_row_mode:
                sys.stdout.write("\r>" + "".join(formatted_values))
            else:
                sys.stdout.write(
                    "".join(formatted_values) + (CURSOR_UP_N_ROWS % len(options_desc))
                )
            sys.stdout.flush()
            # get keyboard input
            req = sys.stdin.read(1)
            if req == "\r":  # <enter>: validate
                break
            elif req in ("A", "D"):  # <up> or <left>: previous
                selected = max(selected - 1, 0)
            elif req in ("B", "C"):  # <down> or <right>: next
                selected = min(selected + 1, len(options_desc) - 1)
            elif allow_ctrl_c and req == '\x03':
                selected = None
                break
    finally:
        if single_row_mode:
            print()
        else:
            sys.stdout.write(CURSOR_DOWN_N_ROWS % len(options_desc))
        sys.stdout.write(CURSOR_VISIBLE)
        tty.restore()
        print()
    if selected is None:
        return None
    if options_values is None:
        return options_desc[selected]
    else:
        return options_values[selected]


@contextmanager
def on_sigwinch_call(handler):
    from signal import signal, SIGWINCH
    prev_on_sigwinch = signal(SIGWINCH, handler)
    yield
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
