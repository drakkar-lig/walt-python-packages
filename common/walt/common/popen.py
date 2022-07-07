import os, shlex

class BetterPopen:
    def __init__(self, cmd, kill_function, shell=True):
        self.kill_function = kill_function
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
    def close(self):
        # call kill function
        if self.return_code is None:
            try:
                self.kill_function(self)
            except Exception as e:
                print('filesystem.close() -- ignored exception:', e)
        # close our ends of the pipes
        for f in self.stdin, self.stdout:
            if f is not None:
                try:
                    f.close()
                except Exception as e:
                    print('filesystem.close() -- ignored exception:', e)
        self.stdin, self.stdout = None, None
        # wait for end of child
        if self.return_code is None:
            try:
                self.wait()
            except Exception as e:
                print('filesystem.close() -- ignored exception:', e)
