"""Record the execution path of python code.

Example:

    import trackexec
    import mypackage

    with trackexec.recording("/tmp/my-trace", include=[mypackage]):
        mypackage.main()

Then replay the trace with `trackexec replay /tmp/my-trace`.
"""
import sys
from contextlib import contextmanager
from importlib.util import find_spec
from os.path import abspath, isdir, isfile
from pathlib import Path

from trackexec.recorder import TrackExecRecorder, DEFAULT_GAP_THRESHOLD

__all__ = ["start", "stop", "recording", "precise_timestamping", "record"]


def _dir_prefix(path):
    return abspath(path).rstrip("/") + "/"


def _resolve_include_item(item):
    """Return (dirs, files) for a module, a package, a module name,
    or a file or directory path."""
    if isinstance(item, type(sys)):
        paths = list(getattr(item, "__path__", ()))
        if len(paths) > 0:
            return [_dir_prefix(p) for p in paths], []
        filename = getattr(item, "__file__", None)
        if filename is None:
            raise ValueError(f"Cannot locate the source code of {item!r}.")
        return [], [abspath(filename)]
    path = str(item)
    if isdir(path):
        return [_dir_prefix(path)], []
    if isfile(path):
        return [], [abspath(path)]
    # not a path, consider it is a module name
    try:
        spec = find_spec(path)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        raise ValueError(f"No such file, directory or module: {path}")
    if spec.submodule_search_locations:
        return [_dir_prefix(p) for p in spec.submodule_search_locations], []
    if spec.origin is None or not isfile(spec.origin):
        raise ValueError(f"Cannot locate the source code of module {path}.")
    return [], [abspath(spec.origin)]


def _resolve_include(include):
    if not isinstance(include, (list, tuple, set, frozenset)):
        include = [include]
    dirs, files = [], []
    for item in include:
        item_dirs, item_files = _resolve_include_item(item)
        dirs += item_dirs
        files += item_files
    if len(dirs) + len(files) == 0:
        raise ValueError("Nothing to trace (empty include list).")
    return dirs, files


def _start(calling_frame, trace_dir, include, module_level, gap_threshold):
    dirs, files = _resolve_include(include)
    module_level_files = [abspath(f) for f in module_level]
    TrackExecRecorder.start_recording(
        calling_frame, Path(trace_dir), dirs, files, module_level_files,
        gap_threshold)


def start(trace_dir, include, *, module_level=(),
          gap_threshold=DEFAULT_GAP_THRESHOLD):
    """Start recording the execution of the current thread into
    trace_dir.

    include is a module, a package, a module name, a file path or
    a directory path, or a list of these items. Only the code of these
    items is recorded.

    Module-level code (i.e., code executed when a module is imported)
    is not recorded, except for the source files listed in module_level.

    Timestamps are only recorded from time to time, and the analysis
    interpolates the time of instructions between them. However, when an
    instruction takes more than gap_threshold seconds (e.g., waiting for
    I/O or calling a slow function which is not recorded), its start and
    end timestamps are recorded. Use None to disable this.

    Raises FileExistsError if trace_dir already contains a trace.
    """
    _start(sys._getframe(1), trace_dir, include, module_level, gap_threshold)


def stop():
    """Stop recording and flush the trace files."""
    TrackExecRecorder.stop()


@contextmanager
def recording(trace_dir, include, *, module_level=(),
              gap_threshold=DEFAULT_GAP_THRESHOLD):
    """Context manager calling start() and stop()."""
    # sys._getframe(2) is the frame of the 'with' statement
    # (frame 1 is contextlib code)
    _start(sys._getframe(2), trace_dir, include, module_level, gap_threshold)
    try:
        yield
    finally:
        stop()


def precise_timestamping():
    """Return a context manager enclosing a code section where
    a timestamp should be recorded at each line of code."""
    return TrackExecRecorder.precise_timestamping()


def record(mod_or_package, dir_path):
    """Former API, equivalent to start(dir_path, mod_or_package)."""
    _start(sys._getframe(1), dir_path, mod_or_package, (),
           DEFAULT_GAP_THRESHOLD)
