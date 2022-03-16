import os
from time import time
from subprocess import Popen, STDOUT, TimeoutExpired

def pipe():
    r, w = os.pipe()
    f_r = os.fdopen(r, mode='rb', buffering=0)
    f_w = os.fdopen(w, mode='wb', buffering=0)
    return f_r, f_w

class BetterPopen:
    def __init__(self, cmd, kill_function):
        self.kill_function = kill_function
        self.f_stdin_r, self.f_stdin_w = pipe()
        self.f_stdout_r, self.f_stdout_w = pipe()
        # os.setpgrp(): signals should not be propagated to child process
        self.proc = Popen(cmd, preexec_fn=os.setpgrp, shell=True,
                    stdin=self.f_stdin_r, stdout=self.f_stdout_w, stderr=STDOUT)
    @property
    def stdin(self):
        return self.f_stdin_w
    @property
    def stdout(self):
        return self.f_stdout_r
    def send_signal(self, sig):
        self.proc.send_signal(sig)
    def poll(self):
        return self.proc.poll()
    def __del__(self):
        self.close()
    def close(self):
        if getattr(self, 'proc', None) is not None:
            # call kill function
            self.kill_function(self)
            proc = self.proc
            self.proc = None
            # close our ends of the pipes
            if not self.f_stdin_w.closed:
                self.f_stdin_w.close()
            if not self.f_stdout_r.closed:
                self.f_stdout_r.close()
            # wait for end of popen process
            proc.wait()
            # close popen ends of the pipes if needed
            if not self.f_stdin_r.closed:
                self.f_stdin_r.close()
            if not self.f_stdout_w.closed:
                self.f_stdout_w.close()

class Filesystem:
    def __init__(self, cmd_interpreter, kill_function):
        self.cmd_interpreter = f'{cmd_interpreter} || echo FAILED'
        self.kill_function = kill_function
        self.popen = None
        self.popen_started = False
    def wrap_cmd(self, cmd):
        return f'{cmd} 2>/dev/null || true\n'
    def check_bg_process_ok(self):
        # check if the running background process is still alive
        if self.popen is not None:
            return_code = self.popen.poll()
            if return_code is None:
                return True     # bg process still alive => no return code yet
            else:
                # background process stopped
                self.close()
        return False
    def send_cmd(self, cmd):
        self.check_bg_process_ok()
        # open or reopen background process if needed
        if self.popen is None:
            self.popen = BetterPopen(self.cmd_interpreter, self.kill_function)
            self.popen.stdin.write(self.wrap_cmd('echo STARTED').encode('ascii'))
        self.popen.stdin.write(self.wrap_cmd(cmd).encode('ascii'))
    def read_reply_line(self):
        for _ in range(100):
            line = self.popen.stdout.readline().decode('ascii').strip()
            if line == 'FAILED':
                self.close()
                return ''
            if self.popen_started:
                return line
            if line == 'STARTED':
                self.popen_started = True
                continue
            if line == '':
                if not self.check_bg_process_ok():
                    return ''
        return ''
    def ping(self, retries=1):
        self.send_cmd('echo ok')
        alive = (self.read_reply_line() == 'ok')
        if not alive:
            self.close()
            if retries > 0:
                return self.ping(retries-1)
        return alive
    def get_file_type(self, path):
        self.send_cmd('find %s' % path)
        if len(self.read_reply_line()) == 0:
            return None
        cmds = []
        for ftype in [ 'f', 'd' ]:
            self.send_cmd('find %(path)s -type %(ftype)s -maxdepth 0 -exec echo -n %(ftype)s \;' % \
                dict(
                    path = path,
                    ftype = ftype
                ))
        self.send_cmd('echo')
        result = self.read_reply_line()
        if len(result) > 0:
            return result
        return 'o'  # other
    def get_completions(self, partial_path):
        """complete a partial path remotely"""
        # the following process allows to add an ending slash to dir entries
        self.send_cmd(f'find {partial_path}* -maxdepth 0 "!" -type d -exec echo "{{}}" \;')
        self.send_cmd(f'find {partial_path}* -maxdepth 0 -type d -exec echo "{{}}/" \;')
        self.send_cmd('echo')
        possible = []
        while True:
            path = self.read_reply_line()
            if path == '':  # empty line marks the end (cf. "echo" above)
                break
            possible.append(path)
        return tuple(possible)
    def close(self):
        if self.popen is not None:
            self.popen.close()
            self.popen = None
            self.popen_started = False

class FilesystemsCache:
    LOOP_RELEASE_PERIOD = 60
    MIN_CACHE_TIME = 180
    def __init__(self, ev_loop, cmd_interpreter_pattern, kill_function):
        self.fs_info = {}
        self.ev_loop = ev_loop
        self.cmd_interpreter_pattern = cmd_interpreter_pattern
        self.kill_function = kill_function
        self.plan_fs_releases()
    def __getitem__(self, fs_id):
        if fs_id not in self.fs_info:
            cmd_interpreter = self.cmd_interpreter_pattern % dict(
                fs_id = fs_id
            )
            self.fs_info[fs_id] = {
                'fs': Filesystem(cmd_interpreter, self.kill_function)
            }
        self.fs_info[fs_id]['last_use'] = time()
        return self.fs_info[fs_id]['fs']
    def __contains__(self, fs_id):
        return fs_id in self.fs_info
    def __delitem__(self, fs_id):
        self.fs_info[fs_id]['fs'].close()
        del self.fs_info[fs_id]
    def plan_fs_releases(self):
        target_ts = time() + FilesystemsCache.LOOP_RELEASE_PERIOD
        # plan event to be called soon
        self.ev_loop.plan_event(
            ts = target_ts,
            target = self
        )
    def handle_planned_event(self):
        # release unused filesystems
        now = time()
        for fs_id, fs_info in tuple(self.fs_info.items()):
            if fs_info['last_use'] + FilesystemsCache.MIN_CACHE_TIME < now:
                fs_info['fs'].close()
                del self.fs_info[fs_id]
        # plan to redo it
        self.plan_fs_releases()
    def cleanup(self):
        for fs_info in self.fs_info.values():
            fs_info['fs'].close()
        self.fs_info = {}
