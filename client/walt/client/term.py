#!/usr/bin/env python
import sys, tty, termios, array, fcntl, curses
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
        buf = array.array('h', [0, 0, 0, 0])
        fcntl.ioctl(self.tty_fd, termios.TIOCGWINSZ, buf, True)
        return buf

@contextmanager
def alternate_screen_buffer():
    sys.stdout.write('\x1b[?1049h')
    yield
    sys.stdout.write('\x1b[?1049l')

def clear_screen():
    sys.stdout.write('\x1b[2J\x1b[H')
