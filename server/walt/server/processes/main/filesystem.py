from time import time

from walt.server.popen import BetterPopen


class Filesystem:
    def __init__(self, ev_loop, cmd_interpreter):
        self.ev_loop = ev_loop
        self.cmd_interpreter = f"{cmd_interpreter} || echo FAILED"
        self.kill_function = lambda popen: popen.stdin.write(b"exit\n")
        self.popen = None
        self.popen_started = False
        self.wf_response_handler = None

    def fileno(self):
        return self.popen.stdout.fileno()

    def wrap_cmd(self, cmd):
        return f"{cmd} 2>/dev/null || true\n"

    def check_bg_process_ok(self):
        # check if the running background process is still alive
        if self.popen is not None:
            if self.popen.is_alive():
                return True  # bg process still alive
            # background process stopped
            self.close()
        return False

    def send_cmd(self, cmd):
        self.check_bg_process_ok()
        # open or reopen background process if needed
        if self.popen is None:
            self.popen = BetterPopen(
                self.ev_loop,
                self.cmd_interpreter,
                self.kill_function,
            )
            self.popen.stdin.write(self.wrap_cmd("echo STARTED").encode("ascii"))
            self.ev_loop.register_listener(self)
        self.popen.stdin.write(self.wrap_cmd(cmd).encode("ascii"))

    def handle_event(self, ts):
        line = self.popen.stdout.readline()
        if len(line) == 0:
            # empty read, close
            return False
        line = line.decode("ascii").strip()
        if line == "FAILED":
            return False  # error
        if line == "STARTED":
            self.popen_started = True
        elif self.wf_response_handler is None:
            # we are no longer waiting for a response!
            return False  # error
        else:
            assert self.popen_started
            self.wf_response_handler.update_env(line=line)
            self.wf_response_handler.next()

    def _wf_handle_ping_reply_line(self, wf, line, retries, **env):
        alive = (line == "ok")
        if not alive:
            self.close()
            if retries > 0:
                wf.update_env(retries=retries-1)
                wf.insert_steps([wf_ping])
                wf.next()
                return
        self.wf_response_handler = None
        wf.update_env(alive=alive)
        wf.next()

    def wf_ping(self, wf, retries=1, **env):
        self.send_cmd("echo ok")
        wf.update_env(retries=retries)
        self.wf_response_handler = wf
        wf.insert_steps([self._wf_handle_ping_reply_line])

    def _wf_handle_file_type_reply_line(self, wf, line, **env):
        ftype = line
        if ftype == "m":  # missing
            ftype = None
        self.wf_response_handler = None
        wf.update_env(ftype=ftype)
        wf.next()

    def wf_get_file_type(self, wf, path, **env):
        self.send_cmd(
            f'if [ -f "{path}" ]; '
            + 'then echo "f"; '
            + f'else if [ -d "{path}" ]; '
            + 'then echo "d"; '
            + f'else if [ -e "{path}" ]; '
            + 'then echo "o"; '
            + 'else echo "m"; '
            + "fi; fi; fi"
        )
        self.wf_response_handler = wf
        wf.insert_steps([self._wf_handle_file_type_reply_line])

    def _wf_handle_completion_reply_line(self, wf, line, remote_completions, **env):
        path = line
        if path == "":  # empty line marks the end (cf. "echo" below)
            self.wf_response_handler = None
            wf.next()
        else:
            remote_completions.append(path)
            # continue with next reply line
            wf.insert_steps([self._wf_handle_completion_reply_line])

    def wf_get_completions(self, wf, partial_path, **env):
        self.send_cmd(
            f'find -L {partial_path}* -maxdepth 0 "!" -type d -exec echo "{{}}" \\;'
        )
        self.send_cmd(
            f'find -L {partial_path}* -maxdepth 0 -type d -exec echo "{{}}/" \\;'
        )
        self.send_cmd("echo")
        self.wf_response_handler = wf
        wf.update_env(remote_completions=[])
        wf.insert_steps([self._wf_handle_completion_reply_line])

    def close(self, cb=None):
        if self.wf_response_handler is not None:
            self.wf_response_handler.interrupt()
        if self.popen is not None:
            self.popen.close(cb=cb)
            self.popen = None
            self.popen_started = False
            self.ev_loop.remove_listener(self)

    def busy(self):
        return self.wf_response_handler is not None


class FilesystemsCache:
    LOOP_RELEASE_PERIOD = 60
    MIN_CACHE_TIME = 180

    def __init__(self, ev_loop, cmd_interpreter_pattern):
        self.fs_info = {}
        self.ev_loop = ev_loop
        self.cmd_interpreter_pattern = cmd_interpreter_pattern
        self.plan_fs_releases()

    def __getitem__(self, fs_id):
        if fs_id not in self.fs_info:
            cmd_interpreter = self.cmd_interpreter_pattern % dict(fs_id=fs_id)
            self.fs_info[fs_id] = {"fs": Filesystem(self.ev_loop, cmd_interpreter)}
        self.fs_info[fs_id]["last_use"] = time()
        return self.fs_info[fs_id]["fs"]

    def __contains__(self, fs_id):
        return fs_id in self.fs_info

    def __delitem__(self, fs_id):
        self.fs_info[fs_id]["fs"].close()
        del self.fs_info[fs_id]

    def plan_fs_releases(self):
        target_ts = time() + FilesystemsCache.LOOP_RELEASE_PERIOD
        # plan event to be called soon
        self.ev_loop.plan_event(ts=target_ts, target=self)

    def handle_planned_event(self):
        # release unused filesystems
        now = time()
        for fs_id, fs_info in tuple(self.fs_info.items()):
            if fs_info["last_use"] + FilesystemsCache.MIN_CACHE_TIME < now:
                if not fs_info["fs"].busy():
                    fs_info["fs"].close()
                    del self.fs_info[fs_id]
        # plan to redo it
        self.plan_fs_releases()

    def cleanup(self):
        for fs_info in self.fs_info.values():
            fs_info["fs"].close()
        self.fs_info = {}
