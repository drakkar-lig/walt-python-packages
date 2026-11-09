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

From the code of the program:

```python
import trackexec
import mypackage

trackexec.record(mypackage, Path("/tmp/my-trace"))
...
trackexec.stop()
```

The program sections where precise timestamps are needed can be enclosed
in `with trackexec.precise_timestamping():`.

trackexec was written for the [WalT project](https://walt-project.liglab.fr).
