import os, shlex, signal
from time import time

# indicate delays between polls and when to send signals when
# terminating the child process.
TERMINATE_EVENTS = ((0.1, None),) * 9 + ((0.1, signal.SIGTERM),) + \
                   ((0.1, None),) * 10 + ((1, None),) * 4 + \
                   ((0.1, signal.SIGKILL),) + ((0.1, None),) * 10

class BetterPopen:
    def __init__(self, ev_loop, cmd, kill_function, shell=True, synchronous_close=False):
        self.ev_loop = ev_loop
        self.kill_function = kill_function
        self._synchronous_close = synchronous_close
        stdin_r, stdin_w = os.pipe()
        stdout_r, stdout_w = os.pipe()
        os.set_inheritable(stdin_r, True)
        os.set_inheritable(stdout_w, True)
        if shell:
            args = [ 'sh', '-c', cmd ]
        else:
            args = shlex.split(cmd)
        pid = os.fork()
        if pid == 0:
            # child
            #print(f'child {os.getpid()}')
            os.close(stdin_w)
            os.close(stdout_r)
            os.dup2(stdin_r, 0)
            os.dup2(stdout_w, 1)
            os.dup2(stdout_w, 2)
            os.execlp(args[0], *args)
        else:
            # parent
            #print(f'parent {os.getpid()}')
            os.close(stdin_r)
            os.close(stdout_w)
            self.child_pid = pid
            self.stdin = os.fdopen(stdin_w, mode='wb', buffering=0)
            self.stdout = os.fdopen(stdout_r, mode='rb', buffering=0)
            self.return_code = None
    def send_signal(self, sig):
        os.kill(self.child_pid, sig)
    def poll(self):
        if self.return_code is None:
            pid, exit_status = os.waitpid(self.child_pid, os.WNOHANG)
            if pid != 0:    # if 0, child is still running
                self.return_code = exit_status >> 8
        return self.return_code
    def wait(self):
        if self.return_code is None:
            pid, exit_status = os.waitpid(self.child_pid, 0)
            self.return_code = exit_status >> 8
    def __del__(self):
        #print(f'__del__ {os.getpid()}')
        self.close()
    def close(self, cb=None):
        if cb is None:
            cb = lambda: None
        # call kill function
        if self.return_code is None:
            try:
                self.kill_function(self)
            except Exception as e:
                print('popen.close() -- ignored exception:', e)
        # close our ends of the pipes
        for f in self.stdin, self.stdout:
            if f is not None:
                try:
                    f.close()
                except Exception as e:
                    print('popen.close() -- ignored exception:', e)
        self.stdin, self.stdout = None, None
        # if child is still alive, fallback to terminate()
        if self.return_code is None:
            if self._synchronous_close:
                print('popen wait -- synchronous close')
                self.wait()
                print('popen wait completed')
                cb()
            else:
                self.plan_terminate(TERMINATE_EVENTS, cb)
        else:
            cb()
    def plan_terminate(self, terminate_events, cb):
        delay, sig = terminate_events[0]
        next_ts = time() + delay
        self.ev_loop.plan_event(
            ts = next_ts,
            callback = self.terminate,
            terminate_events = terminate_events,
            cb = cb)
    def terminate(self, terminate_events, cb):
        try:
            self.poll()
            if self.return_code is not None:
                cb()
                return  # ok child has terminated
            evt, next_evts = terminate_events[0], terminate_events[1:]
            delay, sig = evt
            if sig is not None:
                self.send_signal(sig)
            if len(next_evts) == 0:
                print('popen wait -- end of termination events')
                self.wait()
                print('popen wait completed')
                cb()
                return
            # recall self.terminate() with next events after a delay
            self.plan_terminate(next_evts, cb)
        except Exception as e:
            print('popen.terminate() -- ignored exception:', e)
