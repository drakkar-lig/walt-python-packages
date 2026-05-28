#!/usr/bin/env python3
"""
walt-image-build-runtime: OCI runtime able to run Dockerfile
RUN commands on a remote WALT node when the command is prefixed
with --on-node, and delegates to runc for all other RUN commands.

The runtime also allows to record the value of the --pid-file
option, so that the server is able to kill the process of a
RUN command when the user presses ctrl-C during "walt image build".
(That is also handled for standard RUN commands delegated to runc.)

This script is called by walt-image-shell-helper, which:
- replaces "--on-node" by "__on_node__" because buildah does
  not allow us to add our own RUN option name.
- adds "--network host" build option. Without it, an interrupted
  build leaves a stale eth0/veth0 pair in the host namespace that
  breaks subsequent builds.
"""
# do this asap to avoid early interrupts
import signal
signal.signal(signal.SIGINT, signal.SIG_IGN)

from contextlib import contextmanager
from pathlib import Path

import fcntl
import json
import os
import shlex
import subprocess
import sys
import time

from walt.common.api import api, api_expose_attrs, api_expose_method
from walt.common.apilink import BaseAPIService, ServerAPILink, ExposedStream
from walt.server.exttools import buildah, podman, findmnt, find
from walt.server.mount.setup import setup

TMP_DIR = Path(os.environ.get("RUNTIME_WORKDIR", "/tmp"))
LOG_PATH = TMP_DIR / "walt-runtime.log"
RUNTIME_COMMANDS = ("create", "start", "state", "kill", "delete", "bg-process")
FILE_UPDATE_LOCK_PATH = TMP_DIR / "file-update.lock"
SESSION_ID = int(os.environ.get("WALT_BUILD_SESSION_ID"))


@contextmanager
def file_update_lock():
    FILE_UPDATE_LOCK_PATH.touch()
    with FILE_UPDATE_LOCK_PATH.open() as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
        fcntl.flock(fd, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Let the server print log lines on our output streams
@api
class LocalLoggingService(BaseAPIService):
    @api_expose_attrs("stdout", "stderr")
    def __init__(self):
        super().__init__()
        self.stderr = ExposedStream(sys.stderr)
        self.stdout = ExposedStream(sys.stdout)

    @api_expose_method
    def get_username(self):
        return os.environ.get("WALT_USER")

    @api_expose_method
    def set_busy_label(self, label):
        pass


class LoggingStderr:
    def write(self, s):
        with file_update_lock():
            try:
                sys.__stderr__.write(s)
                sys.__stderr__.flush()
            except OSError:
                pass
            with LOG_PATH.open("a") as log_file:
                log_file.write(s)
                log_file.flush()
    def flush(self):
        pass


def redirect_stderr() -> None:
    sys.stderr = LoggingStderr()


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------

def parse_argv(args: list[str]) -> tuple[str, list[str]]:
    """
    Return (command, cmd_args) by skipping global flags that appear before
    the command name.
    """
    i = 0
    for i, arg in enumerate(args):
        if arg in RUNTIME_COMMANDS:
            return arg, args[i+1:]
    raise Exception("Did not find a command in the given arguments.")


def get_flag(cmd_args: list[str], flag: str) -> str | None:
    """Return the value of a named flag from command-specific args, or None."""
    for i, a in enumerate(cmd_args):
        if a == flag and i + 1 < len(cmd_args):
            return cmd_args[i + 1]
        if a.startswith(f"{flag}="):
            return a[len(flag) + 1:]
    return None


def get_bundle(cmd_args: list[str]) -> str:
    return get_flag(cmd_args, "--bundle") or os.getcwd()


# ---------------------------------------------------------------------------
# Status files
# ---------------------------------------------------------------------------

@contextmanager
def get_container_status_path(container_id):
    with file_update_lock():
        yield TMP_DIR / (container_id + ".status")


@contextmanager
def get_build_mode_path(container_id):
    with file_update_lock():
        yield TMP_DIR / (container_id + ".mode")


@contextmanager
def get_bg_process_pid_path(container_id):
    with file_update_lock():
        yield TMP_DIR / (container_id + ".rpid")


def get_container_status(container_id):
    try:
        with get_container_status_path(container_id) as p:
            return p.read_text()
    except FileNotFoundError:
        return "stopped"


def write_container_status(container_id, status):
    with get_container_status_path(container_id) as p:
        p.write_text(status)


def get_bg_process_pid(container_id):
    with get_bg_process_pid_path(container_id) as p:
        if not p.exists():
            return None
        return int(p.read_text().strip())


def save_bg_process_pid(container_id, pid, cmd_args: list[str]):
    pid_file = get_flag(cmd_args, "--pid-file")
    if pid_file:
        Path(pid_file).write_text(f"{pid}")
        with get_bg_process_pid_path(container_id) as p:
            p.symlink_to(pid_file)
    else:
        with get_bg_process_pid_path(container_id) as p:
            p.write_text(f"{pid}")


# ---------------------------------------------------------------------------
# Other tools
# ---------------------------------------------------------------------------

def exec_runc():
    # re-enable SIGINT, let runc manage it as it is used to
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    # exec runc with the same cli parameters
    os.execv("/usr/sbin/runc", ["/usr/sbin/runc"] + sys.argv[1:])


def run_bg_process(cmd_args):
    p = subprocess.Popen(
        [sys.argv[0], "bg-process"] + cmd_args,
        start_new_session=True,
    )
    return p.pid


def get_mode(container_id, command, cmd_args: list[str]):
    # "create":
    # -> we can check with cli args if the mode is "runc" or "on-node",
    #    then save this mode in a file at get_build_mode_path(<cid>)
    if command == "create":
        config = parse_config(cmd_args)
        mode = config["mode"]
        with get_build_mode_path(container_id) as p:
            p.write_text(mode)
        return mode
    # "bg-process":
    # -> only called when mode=="on-node"
    if command == "bg-process":
        return "on-node"
    # other commands:
    # -> check mode in the file at get_build_mode_path(<cid>)
    with get_build_mode_path(container_id) as p:
        mode = p.read_text().strip()
    return mode


def parse_config(cmd_args):
    bundle = get_bundle(cmd_args)

    # Parse and log config.json.
    config_path = Path(bundle) / "config.json"
    raw = config_path.read_text()
    cfg = json.loads(raw)

    # sample line in Dockerfile:
    # RUN echo 'a b'
    # resulting command args:
    # ["sh", "-c", "echo 'a b'"]
    # Since we'll run the command on the real node
    # we have to get rid of the interpreter part.
    # On a freebsd image it would be
    # ["qemu-<something>", "sh", "-c", "echo 'a b'"].
    # We keep only the initial line of the Dockerfile,
    # i.e., the last arg.
    # note: using shlex.split() could cause problems,
    # because run_args might not be just a command
    # but a whole shell script line such as
    # <cmd1> && <cmd2>.
    process = cfg.get("process", {})
    run_cwd = process.get('cwd', '/')
    run_args = process['args'][-1].strip()
    if run_args.startswith('__on_node__'):
        mode = "on_node"
        run_args = run_args[len('__on_node__'):].lstrip()
    else:
        mode = "runc"
    return {
        "run_args": run_args,
        "run_cwd": run_cwd,
        "mode": mode,
    }


def _signal_bg_process(container_id: str, sig: signal.Signals) -> None:
    """Send sig to the bg-process process group, ignoring errors if already gone."""
    pid = get_bg_process_pid(container_id)
    if pid is None:
        return
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
    except (ProcessLookupError, ValueError, OSError):
        pass


def _kill_bg_process(container_id):
    """Send SIGTERM to the bg-process process group and wait for it to stop.
    Falls back to SIGKILL + manual state update if it doesn't exit in time."""
    _signal_bg_process(container_id, signal.SIGTERM)
    # Wait up to 2 s for bg-process to acknowledge SIGTERM and clean up.
    for _ in range(20):
        time.sleep(0.1)
        pid = get_bg_process_pid(container_id)
        if pid is None:
            break  # bg-process removed its own pid file: it exited cleanly.
        try:
            os.kill(pid, 0)  # probe: raises ProcessLookupError if gone
        except (ProcessLookupError, FileNotFoundError, ValueError):
            break
    else:
        # Timed out: force-kill and mark stopped ourselves.
        _signal_bg_process(container_id, signal.SIGKILL)
        write_container_status(container_id, "stopped")


def get_intermediate_image_info():
    # Note: podman build already provides us a rootfs path in the bundle,
    # but the content of this rootfs mount is only accessible from this
    # process and its children, because of the separate mount namespace.
    # So we cannot use it as an NFS export.
    # Instead, we use buildah commands to retrieve information about
    # the container which was just created and check where its rootfs
    # was mounted in the root namespace.
    container_conf = json.loads(buildah.containers("--json"))[-1]
    container_id = container_conf["id"]
    shared_rootfs = json.loads(buildah.inspect(container_id))["MountPoint"]
    image_id = container_conf["imageid"]
    size_kib = json.loads(podman.inspect(image_id))[0]["Size"] // 1024
    return shared_rootfs, image_id, size_kib


def write_run_on_node_script(rootfs, run_args, run_cwd):
    script_path = Path(rootfs) / ".run-on-node.sh"
    escaped_run_cwd = shlex.join((run_cwd,))
    # Notes:
    # - we should not use "exec <run-args>" because
    #   <run-args> might actually be something like
    #   <cmd1> && <cmd2>; we just let the shell handle it.
    # - we wait a little time after the command has completed
    #   to be sure side-effects are taken into account.
    #   (e.g., buffered psql changes not yet applied by the server).
    script_path.write_text(
        "#!/bin/sh\n"
        "set -e\n"
       f"cd {escaped_run_cwd}\n"
       f"{run_args}\n"
        "busybox sleep 1\n")
    script_path.chmod(0o775)


def get_upperdir(mountpoint):
    mount_info = json.loads(findmnt("--json", mountpoint))["filesystems"][0]
    for mount_option in mount_info["options"].split(","):
        if mount_option.startswith("upperdir="):
            return Path(mount_option[len("upperdir="):])
    raise Exception("Failed to find upperdir!")


def get_upperdir_status(upperdir):
    """Explore upperdir and return a description of its content."""
    # We return a set of bytestrings with format b'<file-path>|<attrs>'.
    # Notes:
    # - About selected stat fields:
    #   %n: file path
    #   %f: file type and mode, 4 hex chars
    #       if the 1st hex char is 2, it's a character device
    #       (see man 7 inode; but note that values are given in
    #       octal in this man page, so 3 bits per digit).
    #   %Hr,%Lr: major and minor numbers, decimal
    #   %y,%z: times of last data modification and status change
    #       we use the human readable form because the alternative
    #       forms %Y and %Z give seconds since Epoch without
    #       subsecond precision.
    # - Files represented as character device files with major and
    #   minor numbers set to zero are whiteout files.
    out = subprocess.check_output(
                f'cd {upperdir} && '
                 'find . -mindepth 1 ! -print0 | '
                    'xargs -0 stat --printf "%n|%f%Hr%Lr %y %z\\0"',
                shell=True)
    return set(out.rstrip(b'\x00').split(b'\x00'))


def cleanup_upperdir(upperdir, old_status, new_status):
    """Cleanup upperdir leaving only the changes due to the command."""
    # old_status: status of files just after the setup procedure.
    # new_status: status of files after booting and running the command.

    # Keeping only the file changes due to the command is not reliable.
    # For instance, if the command is psql used to restore a db backup,
    # the bootup may initialize postgresql server files as a 1st boot
    # procedure, and reverting those 1st boot changes while keeping
    # only the new changes will mostly not result in a valid state.
    # That's why we revert only the changes due to the setup() procedure.

    # Since we are considering the upperdir of the overlay,
    # the files we observe there only correspond to changes
    # relative to the files of the OS image.

    # Considering the versions of a given file, we have the
    # following cases (here "cmd" actually means "bootup or command"):
    # old | new
    #  ø  |  A   -- (a) created/modified by cmd
    #  A  |  A   -- (b) created/modified before cmd (by setup())
    #  A  |  A'  -- (c) created/modified before and then again by cmd
    #  A  |  ø   -- (d) created/modified before but removed/restored by cmd

    # Cases (c) & (d) should be very unusual.

    # We must clean things up only in case (b). So the files we will
    # clean up can be obtained by computing the intersection of the
    # two statuses.

    # last important thing: creating/modifying a file on the mountpoint
    # may trigger the creation of one or several directories on the
    # upperdir to match the file path. Those directories should not
    # be considered as changes over the OS image.
    # It's hard to know if directories are real new directories or
    # if they were just created because of this mechanism.
    # As an heuristic, we remove only the ones matching 2 conditions:
    # - belong to the intersection of the two statuses (same as other
    #   files).
    # - be empty after having cleaned up the other files, assuming
    #   we work in a depth-first manner (see 'sort -z -r' below).
    # Directories correspond to the file type "4".
    preserved_status = old_status & new_status
    paths_and_types = [(path, stats.startswith(b'4'))
                       for path, stats in (
                           file_desc.rsplit(b'|')
                           for file_desc in preserved_status
                       )]
    file_paths = b'\x00'.join(
            path for path, is_dir in paths_and_types if not is_dir
    )
    subprocess.run(f'cd {upperdir} && '
                    'xargs -0 rm -f',
                    input=file_paths, shell=True)

    dir_paths = b'\x00'.join(
            path for path, is_dir in paths_and_types if is_dir
    )
    subprocess.run(f'cd {upperdir} && '
                    'sort -z -r | '
                    'find -files0-from - -maxdepth 0 -empty -delete',
                    input=dir_paths, shell=True)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def on_node_create(container_id, cmd_args: list[str]) -> None:
    config = parse_config(cmd_args)
    pid = run_bg_process(cmd_args)
    save_bg_process_pid(container_id, pid, cmd_args)
    write_container_status(container_id, "created")


def on_node_start(container_id) -> None:
    # Only advance from "created" to "running"; don't overwrite "stopped".
    if get_container_status(container_id) == "created":
        write_container_status(container_id, "running")


def on_node_state(container_id: str) -> None:
    status = get_container_status(container_id)
    state = {
        "id": container_id,
        "status": status,
        "bundle": "",
    }
    print(json.dumps(state))  # Must go to stdout per OCI spec.


def on_node_bg_process(container_id, cmd_args: list[str]) -> None:

    def _mark_stopped():
        write_container_status(container_id, "stopped")
        with get_bg_process_pid_path(container_id) as p:
            p.unlink(missing_ok=True)

    def sigterm_handler(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        _mark_stopped()
        sys.exit(1)

    signal.signal(signal.SIGTERM, sigterm_handler)

    retcode = 1   # failure
    log("Preparing intermediate image for node bootup...")
    rootfs, image_id, size_kib = get_intermediate_image_info()
    # image setup() is done here and not on server side
    # because it might block a little time depending on the
    # OS image content.
    setup(image_id, rootfs, size_kib, log)
    config = parse_config(cmd_args)
    run_args = config["run_args"]
    run_cwd = config["run_cwd"]
    write_run_on_node_script(rootfs, run_args, run_cwd)
    upperdir = get_upperdir(rootfs)
    old_status = get_upperdir_status(upperdir)
    local_service = LocalLoggingService()
    with ServerAPILink("localhost", "SSAPI", local_service) as server:
        server.image_build_run_on_node_prepare(SESSION_ID, rootfs)
        retcode = server.image_build_run_on_node_run_cmd(SESSION_ID)
        if retcode == 0:
            new_status = get_upperdir_status(upperdir)
            log("Filtering out file changes not due to command...")
            cleanup_upperdir(upperdir, old_status, new_status)
        server.image_build_run_on_node_cleanup(SESSION_ID)
    _mark_stopped()
    sys.exit(retcode)


def on_node_kill(container_id) -> None:
    _kill_bg_process(container_id)


def on_node_delete(container_id) -> None:
    """Kill (in case "kill" command was not called) and cleanup."""
    _kill_bg_process(container_id)
    with get_bg_process_pid_path(container_id) as p:
        p.unlink(missing_ok=True)
    with get_container_status_path(container_id) as p:
        p.unlink(missing_ok=True)
    with get_build_mode_path(container_id) as p:
        p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    redirect_stderr()

    args = sys.argv[1:]
    command, cmd_args = parse_argv(args)

    # OCI kill syntax: kill <container-id> <signal>
    # The container-id is the first positional arg; for all other commands it
    # is the last arg.
    if command == "kill":
        container_id = cmd_args[0]
    else:
        container_id = cmd_args[-1]

    # let the server save the pid file to be able to kill the process
    # if needed
    if command == "create":
        pid_file = get_flag(cmd_args, "--pid-file")
        if pid_file:
            with ServerAPILink("localhost", "SSAPI") as server:
                server.image_build_save_pid_file(SESSION_ID, pid_file)

    mode = get_mode(container_id, command, cmd_args)

    # if mode is "runc", just exec it
    if mode == "runc":
        exec_runc()
    else:
        match command:
            case "create":
                on_node_create(container_id, cmd_args)
            case "start":
                on_node_start(container_id)
            case "state":
                on_node_state(container_id)
            case "kill":
                on_node_kill(container_id)
            case "delete":
                on_node_delete(container_id)
            case "bg-process":
                on_node_bg_process(container_id, cmd_args)
            case _:
                log(f"  unrecognised command {command!r} — ignoring")


if __name__ == "__main__":
    run()
