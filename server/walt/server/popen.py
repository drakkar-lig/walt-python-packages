import os
import shlex
import signal
from time import time

# indicate delays between checks and when to send signals when
# force-terminating the child process.
TERMINATE_EVENTS = (
    (3.0, signal.SIGTERM),
    (5.0, signal.SIGKILL),
    (2.0, None)  # detect failure to kill
)


class BetterPopen:
    _instances = {}
    def __init__(
        self, ev_loop, cmd, kill_function, shell=True
    ):
        self.ev_loop = ev_loop
        self.kill_function = kill_function
        self.cmd = cmd
        stdin_r, stdin_w = os.pipe()
        stdout_r, stdout_w = os.pipe()
        os.set_inheritable(stdin_r, True)
        os.set_inheritable(stdout_w, True)
        if shell:
            args = ["sh", "-c", cmd]
        else:
            args = shlex.split(cmd)
        pid = os.fork()
        if pid == 0:
            # child
            # print(f'child {os.getpid()}')
            os.setpgrp()
            os.close(stdin_w)
            os.close(stdout_r)
            os.dup2(stdin_r, 0)
            os.dup2(stdout_w, 1)
            os.dup2(stdout_w, 2)
            os.execlp(args[0], *args)
        else:
            # parent
            # print(f'parent {os.getpid()}')
            os.close(stdin_r)
            os.close(stdout_w)
            self.child_pid = pid
            self.child_pidfd = os.pidfd_open(pid, 0)
            self.child_stopped = False
            self.stdin = os.fdopen(stdin_w, mode="wb", buffering=0)
            self.stdout = os.fdopen(stdout_r, mode="rb", buffering=0)
            self._closing = False
            self._closing_callbacks = []
            ev_loop.register_listener(self)
            BetterPopen._instances[id(self)] = self

    def fileno(self):
        return self.child_pidfd

    def is_alive(self):
        return not self.child_stopped

    def handle_event(self, ts):
        # the event loop calls this when the child is stopped
        os.waitpid(self.child_pid, 0)
        self.child_stopped = True
        return False  # let the event loop remove us and call close()

    def send_signal(self, sig):
        assert self.child_pid is not None
        try:
            os.kill(self.child_pid, sig)
        except OSError:
            print(
                f"Sending signal {sig} to pid {self.child_pid} failed. Process is"
                " probably gone already."
            )

    def __del__(self):
        if not self.child_stopped:
            print(f"Popen object not cleanly terminated: {self.cmd}")

    def close(self, cb=None):
        if cb is not None:
            self._closing_callbacks.append(cb)
        if self.child_stopped:
            self.real_end()
            return
        if self._closing:
            # already closing
            return
        self._closing = True
        # call kill function
        try:
            self.kill_function(self)
        except Exception as e:
            print("popen.close() -- ignored exception:", e)
        self.plan_terminate(TERMINATE_EVENTS)

    def real_end(self):
        for f in self.stdin, self.stdout:
            if f is not None:
                try:
                    f.close()
                except Exception as e:
                    print("popen.close() -- ignored exception:", e)
        self.stdin, self.stdout = None, None
        if self.child_pidfd is not None:
            os.close(self.child_pidfd)
            self.child_pidfd = None
        self.call_closing_callbacks()
        if id(self) in BetterPopen._instances:
            del BetterPopen._instances[id(self)]

    @classmethod
    def can_end_evloop(cls):
        return len(BetterPopen._instances) == 0

    def plan_terminate(self, terminate_events):
        delay, sig = terminate_events[0]
        next_ts = time() + delay
        self.ev_loop.plan_event(
            ts=next_ts,
            callback=self.terminate,
            terminate_events=terminate_events
        )

    def terminate(self, terminate_events):
        if self.is_alive():  # if child is still alive
            try:
                evt, next_evts = terminate_events[0], terminate_events[1:]
                delay, sig = evt
                if sig is not None:
                    self.send_signal(sig)
                if len(next_evts) == 0:
                    raise Exception("Could not terminate popen child!")
                else:
                    # recall self.terminate() with next events after a delay
                    self.plan_terminate(next_evts)
                    return
            except Exception as e:
                print("popen.terminate() -- ignored exception:", e)

    def call_closing_callbacks(self):
        self._closing_callbacks, callbacks = ([], self._closing_callbacks)
        for cb in callbacks:
            cb()
