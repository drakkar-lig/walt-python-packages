from time import time

from walt.server.popen import BetterPopen


class Filesystem:
    def __init__(self, ev_loop, cmd_interpreter):
        self.ev_loop = ev_loop
        self.cmd_interpreter = f"{cmd_interpreter} || echo FAILED"
        self.kill_function = lambda popen: popen.stdin.write(b"exit\n")
        self.popen = None
        self.popen_started = False

    def wrap_cmd(self, cmd):
        return f"{cmd} 2>/dev/null || true\n"

    def check_bg_process_ok(self):
        # check if the running background process is still alive
        if self.popen is not None:
            try:
                if self.popen.poll():
                    return True  # bg process still alive
            except Exception:
                pass
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
                synchronous_close=True,
            )
            self.popen.stdin.write(self.wrap_cmd("echo STARTED").encode("ascii"))
        self.popen.stdin.write(self.wrap_cmd(cmd).encode("ascii"))

    def read_reply_line(self):
        for _ in range(100):
            line = self.popen.stdout.readline().decode("ascii").strip()
            if line == "FAILED":
                self.close()
                return ""
            if self.popen_started:
                return line
            if line == "STARTED":
                self.popen_started = True
                continue
            if line == "":
                if not self.check_bg_process_ok():
                    return ""
        return ""

    def ping(self, retries=1):
        self.send_cmd("echo ok")
        alive = self.read_reply_line() == "ok"
        if not alive:
            self.close()
            if retries > 0:
                return self.ping(retries - 1)
        return alive

    def get_file_type(self, path):
        # f: regular; d: directory; o: other; m: missing
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
        ftype = self.read_reply_line()
        if ftype == "m":  # missing
            return None
        else:
            return ftype

    def get_completions(self, partial_path):
        """complete a partial path remotely"""
        # the following process allows to add an ending slash to dir entries
        self.send_cmd(
            f'find {partial_path}* -maxdepth 0 "!" -type d -exec echo "{{}}" \\;'
        )
        self.send_cmd(
            f'find {partial_path}* -maxdepth 0 -type d -exec echo "{{}}/" \\;'
        )
        self.send_cmd("echo")
        possible = []
        while True:
            path = self.read_reply_line()
            if path == "":  # empty line marks the end (cf. "echo" above)
                break
            possible.append(path)
        return tuple(possible)

    def close(self, cb=None):
        if self.popen is not None:
            self.popen.close(cb=cb)
            self.popen = None
            self.popen_started = False


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
                fs_info["fs"].close()
                del self.fs_info[fs_id]
        # plan to redo it
        self.plan_fs_releases()

    def cleanup(self):
        for fs_info in self.fs_info.values():
            fs_info["fs"].close()
        self.fs_info = {}
