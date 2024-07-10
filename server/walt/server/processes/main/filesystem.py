from time import time

from walt.server.popen import BetterPopen


class Filesystem:
    def __init__(self, ev_loop, cmd_interpreter):
        self.ev_loop = ev_loop
        self.cmd_interpreter = f"{cmd_interpreter} || echo FAILED"
        self.kill_function = lambda popen: popen.stdin.write(b"exit\n")
        self.popen = None
        self.wf_response_handler = None

    def fileno(self):
        return self.popen.stdout.fileno()

    def wrap_cmd(self, cmd):
        return f"{cmd} 2>/dev/null || true\n"

    def send_cmd(self, cmd):
        # check if the running background process is still alive
        if self.popen is not None:
            if not self.popen.is_alive():
                self.popen = None
                self.ev_loop.remove_listener(self, should_close=False)
        # open or reopen background process if needed
        if self.popen is None:
            self.popen = BetterPopen(
                self.ev_loop,
                self.cmd_interpreter,
                self.kill_function,
            )
            self.ev_loop.register_listener(self)
        self.popen.stdin.write(self.wrap_cmd(cmd).encode("ascii"))

    def handle_event(self, ts):
        if self.wf_response_handler is None:
            # unexpected event, let the event loop close us
            return False
        if self.popen is None or not self.popen.is_alive():
            line = "KO"
        else:
            line = self.popen.stdout.readline()
            line = line.decode("ascii").strip()
        self.wf_response_handler.update_env(line=line)
        self.wf_response_handler.next()

    def _wf_handle_ping_reply_line(self, wf, line, retries, **env):
        alive = (line == "ok")
        self.wf_response_handler = None
        if not alive:
            # close background process, to force restarting it
            # in self.send_cmd()
            if self.popen is not None:
                if self.popen.is_alive():
                    self.popen.close()
                self.popen = None
                self.ev_loop.remove_listener(self, should_close=False)
            if retries > 0:
                wf.update_env(retries=retries-1)
                wf.insert_steps([self.wf_ping])
                wf.next()
                return
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

    def close(self):
        if self.wf_response_handler is not None:
            self.wf_response_handler.interrupt()
            self.wf_response_handler = None
        if self.popen is not None:
            self.popen.close()
            self.popen = None

    def busy(self):
        return self.wf_response_handler is not None

    def full_close(self):
        if self.popen is not None:
            self.ev_loop.remove_listener(self, should_close=False)
        self.close()


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
        self.fs_info[fs_id]["fs"].full_close()
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
                    fs_info["fs"].full_close()
                    del self.fs_info[fs_id]
        # plan to redo it
        self.plan_fs_releases()

    def cleanup(self):
        for fs_info in self.fs_info.values():
            fs_info["fs"].full_close()
        self.fs_info = {}
