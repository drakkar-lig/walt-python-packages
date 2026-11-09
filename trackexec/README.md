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
consumed the most execution time.


## Recording a trace

### From the command line

```
trackexec record [-o TRACE_DIR] [-i PATH_OR_MODULE]... SCRIPT [ARG...]
trackexec record [-o TRACE_DIR] [-i PATH_OR_MODULE]... -m MODULE [ARG...]
```

This runs the program (as `python SCRIPT` or `python -m MODULE` would do)
and records its execution. By default, the code recorded is the code in
the directory of SCRIPT, or the code of the top-level package of MODULE.
Use `-i` (repeatable) to select other files, directories or modules.
The trace is saved in `trackexec-<YYMMDD-HHMMSS>` unless `-o` is given.


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

`include` accepts modules, packages, module names, file paths and
directory paths, or a list of them. The code executed at module level
(i.e., when a module is imported) is not recorded, unless its source file
is listed in the `module_level` keyword argument.

Only the thread calling `start()` is recorded, and recording stops in
forked child processes.

The program sections where precise timestamps are needed can be enclosed
in `with trackexec.precise_timestamping():`.

trackexec was written for the [WalT project](https://walt-project.liglab.fr).
