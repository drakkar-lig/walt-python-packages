import os, termios, struct, fcntl, re

TTY_CONTROL_CHARS = ''.join(map(unichr, range(0,32) + range(127,160)))
TTY_CONTROL_CHARS_RE = re.compile('[%s]' % re.escape(TTY_CONTROL_CHARS))

def remove_control_chars(s):
    return TTY_CONTROL_CHARS_RE.sub('', s)

def set_tty_size_raw(fd, tty_size_raw):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, tty_size_raw)

def set_tty_size(fd, tty_size):
    tty_rows, tty_cols = tty_size
    packed = struct.pack("HHHH", tty_rows, tty_cols, 0, 0)
    set_tty_size_raw(fd, packed)

def acquire_controlling_tty(tty_fd):
    # we need to be a session leader
    os.setsid()
    # just opening the file descriptor *without* the flag O_NOCTTY
    # should be enough
    ttyname = os.ttyname(tty_fd)
    os.close(os.open(ttyname, os.O_RDONLY))

def tty_disable_echoctl(fd):
    attrs = termios.tcgetattr(fd)
    attrs[3] = attrs[3] & ~termios.ECHOCTL
    termios.tcsetattr(fd, termios.TCSADRAIN, attrs)

