# trackexec

Record the execution path of python code, then replay it with a
debugger-like interface, or analyse it to find which instructions took
the most time.

The recording is designed to run in production: execution traces are
compact binary files, and the code you want to trace is selected by
package, so the rest of the program (e.g., the standard library or other
libraries) is not traced.


## Replaying a trace

```
trackexec replay TRACE_DIR
```

Use `<n>`, `<s>`, `<c>` (next, step, continue), set breakpoints, and jump
in time (e.g., to a timestamp seen in a log file). Press `<h>` for help.
Replaying a trace has no impact on the traced program, which may still be
running.


## Analysing a trace

```
trackexec analyse TRACE_DIR
```

This displays the "hot points" of the trace, i.e., the instructions which
consumed the most execution time. For each instruction (i.e., source code
line), the following columns are displayed:

* `Cumulated`: total execution time of the instruction, over the whole trace.
* `Average`: average execution time of the instruction.
* `Max`: longest execution time of the instruction; this is the maximum time
  this instruction blocked the program.
* `Frequency`: number of times the instruction was executed (0 for an
  instruction which was already running when the recording started).

The execution time of an instruction includes the time spent in the
functions it calls. If the program was still running at the end of the
trace, the instructions still running are considered with their execution
time so far.

Use `--sort-column` to sort by `cumulated-runtime` (the default),
`average-runtime`, `max-runtime` or `frequency`, and `--num-items` to
select how many instructions are displayed (default: 20).
With `--file-id FILE_ID`, these columns are displayed alongside each line
of the given source file instead (file IDs are listed in the first column
of the default view).

Note that, to limit the overhead, timestamps are only recorded from time
to time, and the execution times of instructions are interpolated between
them. However, when an instruction takes longer than 1 ms (e.g., waiting
for I/O, `time.sleep()`, or calling a slow function which is not
recorded), the recorder detects it and records its exact start and end
timestamps. The time trackexec spends writing the trace files is also
excluded from the execution times.


## Recording a trace

### From the command line

```
trackexec record [-o TRACE_DIR] [-i PATH_OR_MODULE]... [--gap-threshold MS] SCRIPT [ARG...]
trackexec record [-o TRACE_DIR] [-i PATH_OR_MODULE]... [--gap-threshold MS] -m MODULE [ARG...]
```

This runs the program (as `python SCRIPT` or `python -m MODULE` would do)
and records its execution. By default, the code recorded is the code in
the directory of SCRIPT, or the code of the top-level package of MODULE.
Use `-i` (repeatable) to select other files, directories or modules.
The trace is saved in `trackexec-<YYMMDD-HHMMSS>` unless `-o` is given.
Instructions taking longer than `--gap-threshold` (default: 1 ms) get exact
start and end timestamps.


### From the code of the program

```python
import trackexec
import mypackage

with trackexec.recording("/tmp/my-trace", include=mypackage):
    mypackage.main()
```

Or, if start and stop happen at different places:

```python
trackexec.start("/tmp/my-trace", include=[mypackage, "/path/to/script.py"])
...
trackexec.stop()
```

The keyword argument `gap_threshold` (in seconds, default 0.001) is the
duration above which an instruction gets exact start and end timestamps
(`None` disables this).

`include` accepts modules, packages, module names, file paths and
directory paths, or a list of them. The code executed at module level
(i.e., when a module is imported) is not recorded, unless its source file
is listed in the `module_level` keyword argument.

Only the thread calling `start()` is recorded, and recording stops in
forked child processes.

With python 3.12 or later, trackexec relies on `sys.monitoring`, so the
code which is not recorded runs at almost full speed. With older python
versions, or if no `sys.monitoring` tool id is free, it falls back to
`sys.settrace()`. The environment variable `TRACKEXEC_BACKEND` (`auto`,
`monitoring` or `settrace`) allows to force this choice.

trackexec was written for the [WalT project](https://walt-project.liglab.fr).
