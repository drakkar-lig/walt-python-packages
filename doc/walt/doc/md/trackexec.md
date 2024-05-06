
# Repository: walt-python-packages; trackexec tooling.

This section explains how to enable execution tracking of `walt-server-daemon`
sub-processes, how to replay or analyse such a tracked execution, and how
to improve trackexec timestamping.


## Purpose

Trackexec allows to track the execution of `walt-server-daemon` sub-processes,
for post-mortem analysis, understanding an unexpected behavior, or analysing
code performance.

It provides a tool to replay the execution trace, with an interface similar to
a debugger, post mortem or while the process is still running.
It also provides a tool to analyse the trace and find "hot points", i.e. instructions
taking a long time to execute and possibly blocking the process more than expected.


## Enabling trackexec

To enable trackexec, just create the directory `/var/log/walt/trackexec` and restart
`walt-server-daemon` (or on a production server, call `systemctl restart walt-server`).
Each sub-process will then create a new subdirectory at
`/var/log/walt/trackexec/<YYMMDD-HHMMSS>/<sub-process-name>/`,
and start populating it with execution traces.

For convenience, a symlink `/var/log/walt/trackexec/latest` pointing to the last
`<YYMMDD-HHMMSS>` sub-directory is also updated.

Enabling trackexec should **not** slow down WALT server code too much, so do not
hesitate to activate it, even on a production system.

Note: execution traces are not human-readable, use `walt-server-trackexec-replay`.


## Replaying execution traces

To replay, use for instance:
```
$ walt-server-trackexec-replay /var/log/walt/trackexec/latest/server-main
```
This will use the last execution of `server-main` subprocess. The fact
it may still be running is not a problem, the tool will just allow to
browse past execution traces, up to the point the tool was called.

One can obviously replay an older execution, and possibly the execution of
another sub-process, for instance:
```
$ walt-server-trackexec-replay /var/log/walt/trackexec/240416-162041/server-db
```

The command opens a command line interface similar to a debugger. You can press
`<h>` for help. Press `<h>` again to leave the help screen.

Similarly to a debugger, you can press `<n>`, `<s>`, `<c>` for `next`, `step`,
`continue`. You can also insert a `breakpoint` using `b <line>`, and let the
tool stop at this place by pressing `<c>` (i.e., `continue`).
The tool also provides ways to jump in time, in a relative or absolute manner.
See help screen for more info. This is very handy for debugging around a specific
timestamp seen in walt or systemd logs.

Keep in mind that we are just browsing execution traces, so even if the process
is still running, stopping on a breakpoint for instance has no impact on it.


## Analysing execution traces

To analyse, use for instance:
```
$ walt-server-trackexec-analyse /var/log/walt/trackexec/latest/server-main
```

The tool will display a table indicating which python instructions consumed
the most execution time.


## Trackexec in the source code, details about timestamps

Trackexec is activated in the startup code of `walt-server-daemon` subprocesses,
in file `server/walt/server/process.py`. For reducing the disk usage and
preserving performance, trackexec is configured to monitor only the code of the
`walt` package: other libraries are not monitored.
Moreover, timestamps are recorded sparsely.

This initialization code also installs a hook on the event loop for recording
a precise timestamp before and after the event loop is idle.

For efficient indexing, the traces are recorded as blocks.
When a block is started, a timestamp is recorded.
The estimated timestamp of each instruction is computed linearly based on the two
closest timestamps recorded.

For more precise timestamping on a given section of the source code, the developer
may use the following construct:
```
from walt.server.trackexec import precise_timestamping
[...]
def <function>(args):
    [...]
    with precise_timestamping():
        <do-something>
        <do-something-else>
    [...]
```

In this case, a timestamp is recorded before and after each instruction of the
section (including instructions of involved function calls if any).
This can be handy for inspecting a slow function in more details. Without this,
the delay caused by a slow function is spread linearly between the two closest
timestamps recorded.

The hook installed on the event loop actually uses this function `precise_timestamping`.

The code of trackexec itself is at `server/walt/server/trackexec/`.
