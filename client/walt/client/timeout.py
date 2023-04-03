from time import time
from contextlib import contextmanager

MARGIN = 0.001  # margin when testing if timeout is reached
timeout = None

class TimeoutException(Exception):
    pass

def timeout_sighandler(signum, frame):
    raise TimeoutException()

def timeout_init_handler():
    import signal
    signal.signal(signal.SIGALRM, timeout_sighandler)

def start_timeout(secs):
    import signal
    global timeout
    timeout = time() + secs - MARGIN
    signal.alarm(secs)

def stop_timeout():
    import signal
    signal.alarm(0)

def timeout_reached():
    return time() >= timeout

def cli_timeout_switch():
    from plumbum import cli
    return cli.SwitchAttr(
                "--timeout",
                int,
                argname = 'SECONDS',
                default = -1,
                help= """stop if still waiting after this number of seconds""")

@contextmanager
def timeout_context(timeout):
    if timeout > 0:
        start_timeout(timeout)
    try:
        yield
    finally:
        if timeout > 0:
            stop_timeout()
