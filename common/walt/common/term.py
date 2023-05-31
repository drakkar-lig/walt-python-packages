#!/usr/bin/env python
import array
import curses
import fcntl
import sys
import termios
import tty
from contextlib import contextmanager


class TTYSettings(object):
    def __init__(self):
        self.tty_fd = sys.stdout.fileno()
        # save
        self.saved = termios.tcgetattr(self.tty_fd)
        self.win_size = self.get_win_size()
        self.rows, self.cols = self.win_size[0], self.win_size[1]
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

    def get_win_size(self):
        buf = array.array("h", [0, 0, 0, 0])
        fcntl.ioctl(self.tty_fd, termios.TIOCGWINSZ, buf, True)
        return buf


@contextmanager
def alternate_screen_buffer(mouse_wheel_as_arrow_keys=False):
    sys.stdout.write("\x1b[?1049h")
    if mouse_wheel_as_arrow_keys:
        sys.stdout.write("\x1b[?1007h")
    sys.stdout.flush()
    yield
    if mouse_wheel_as_arrow_keys:
        sys.stdout.write("\x1b[?1007l")
    sys.stdout.write("\x1b[?1049l")
    sys.stdout.flush()


def clear_screen():
    sys.stdout.write("\x1b[2J\x1b[H")


NORMAL = "\x1b[0m"
INVERSE = "\x1b[7m"
CURSOR_VISIBLE = "\x1b[?25h"
CURSOR_HIDDEN = "\x1b[?25l"
CURSOR_UP_N_ROWS = "\x1b[%dA"
CURSOR_DOWN_N_ROWS = "\x1b[%dB"


def choose(prompt, options):
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
    finally:
        if single_row_mode:
            print()
        else:
            sys.stdout.write(CURSOR_DOWN_N_ROWS % len(options_desc))
        sys.stdout.write(CURSOR_VISIBLE)
        tty.restore()
        print()
    if options_values is None:
        return options_desc[selected]
    else:
        return options_values[selected]
