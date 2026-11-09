import gzip
import numpy as np
import os
import sys
import tarfile

from array import array
from os import getpid
from os.path import dirname
from threading import get_ident
from time import time
from trackexec.const import (
        OpCodes, MAP_FILE_SIZE, SEC_AS_TS,
        LINENO_UNDEFINED
)
from trackexec.tools import (
        map_block_dt, index_block_dt,
        LogAbstractManagement
)

TRACKEXEC_SRC_PREFIX = dirname(__file__) + "/"

# opcodes as python ints (faster than numpy scalars)
OP_CALL = int(OpCodes.CALL)
OP_RETURN = int(OpCodes.RETURN)
OP_TIMESTAMP = int(OpCodes.TIMESTAMP)

# number of codes kept free at the end of each block, for:
# * possibly enclosing the last instruction with 2 timestamps (2 x 5 codes)
#   when it took longer than the gap threshold (see _record_gap());
# * ending the block with a timestamp (5 codes);
# * at least 1 END opcode.
BLOCK_RESERVE = 16

# default gap threshold (seconds)
DEFAULT_GAP_THRESHOLD = 0.001

# dtype of the call stack saved at the start of each block
STACK_DT = np.dtype([('file_id', np.uint16), ('lineno', np.uint16)])


class TrackExecRecorder(LogAbstractManagement):
    """Base recorder class, which encodes execution events into the trace.
    Subclasses implement the capture of these events (see
    SettraceRecorder and MonitoringRecorder below)."""
    _instance = None

    def __init__(self, dir_path, include_dirs, include_files,
                 module_level_files=(), gap_threshold=DEFAULT_GAP_THRESHOLD):
        """Record the execution of the code in include_dirs (absolute
        directory paths, each ending with "/") and include_files (absolute
        file paths). Module-level code (i.e., the code executed when a
        module is imported) is not recorded, except for the files in
        module_level_files.
        When an instruction takes more than gap_threshold seconds, its
        start and end timestamps are recorded (None disables this)."""
        super().__init__(dir_path)
        if self._log_index_path.exists():
            raise FileExistsError(
                f"{dir_path} already contains an execution trace.")
        dir_path.mkdir(parents=True, exist_ok=True)
        self._include_dirs = tuple(include_dirs)
        self._include_files = frozenset(include_files)
        self._module_level_files = frozenset(module_level_files)
        self._filenames = []
        self._num_saved_filenames = 0
        self._file_id_per_code_id = {}
        self._id_per_filename = {}
        # note: for performance, the recording code uses python lists
        # and arrays, and numpy only when writing a block.
        # call stack: file id and current line number of each frame
        self._stack_file_ids = []
        self._stack_linenos = []
        # codes of the current block
        self._codes = array("H")
        self._map_block = np.zeros(1, dtype=map_block_dt(0))
        self._index_block = np.zeros(1, dtype=index_block_dt())
        self._last_timestamp = None
        self._pid = getpid()
        self._current_lineno = LINENO_UNDEFINED
        # gap detection: time when the last event was captured, and
        # position of the codes of this event in the current block
        if gap_threshold is None:
            gap_threshold = float("inf")
        self._gap_threshold = gap_threshold
        self._t_prev = None
        self._last_event_pos = 0
        (dir_path / "pid").write_text(f"{self._pid}\n")
        self._write_format_version()

    # methods implemented by backends
    # -------------------------------
    def _setup(self):
        """Prepare the backend, before the call stack is analysed"""

    def _enable_frame(self, frame):
        """Enable the recording of a frame already on the call stack"""

    def _on_new_included_code(self, f_code):
        """Called the first time a code object to be recorded is seen"""

    def _enable(self):
        """Start capturing execution events"""

    def _disable(self):
        """Stop capturing execution events"""

    # ------------------------------

    def _recursive_call_stack_init(self, frame):
        # recurse first (register bottom calls of the stack first)
        if frame.f_back is not None:
            self._recursive_call_stack_init(frame.f_back)
        # unless filtered out, add the frame to the call stack
        # and enable tracing on it
        file_id = self._get_file_id(frame.f_code)
        if file_id != -1:
            self._stack_file_ids.append(file_id)
            self._stack_linenos.append(frame.f_lineno)
            self._enable_frame(frame)
            self._current_lineno = frame.f_lineno

    def start(self, calling_frame):
        # when the recorder code is started, we analyse which frames of
        # the call stack match our filtering prefix; those frames are
        # used to initialize our call stack (self._stack_*) and we manually
        # enable tracing on them, in order to capture their execution
        # when this code returns to its caller.
        self._setup()
        self._recursive_call_stack_init(calling_frame)
        self._init_block()
        # enable event capture for next calls
        self._enable()

    def _update_log_sources_archive(self):
        with tarfile.open(self._log_sources_archive_path, "w:gz") as t_w:
            for filename in self._filenames:
                t_w.add(filename)

    def _init_block(self):
        # update the log_index file
        stack_size = len(self._stack_file_ids)
        # we ensure we record a monotonic suite of timestamps
        now = time()
        ts = int(now * SEC_AS_TS)
        if self._last_timestamp is None or ts > self._last_timestamp:
            self._last_timestamp = ts
        self._index_block[0]['timestamp'] = self._last_timestamp
        self._min_stack_size = stack_size
        self._map_block = self._map_block.view(dtype=map_block_dt(stack_size))
        bl_content = self._map_block[0]
        bl_content['stack_size'] = stack_size
        stack = np.empty(stack_size, STACK_DT)
        stack['file_id'] = self._stack_file_ids
        stack['lineno'] = self._stack_linenos
        bl_content['stack'] = stack
        self._max_bytecode_len = len(bl_content['bytecode'])
        self._codes = array("H")
        # the time spent writing the previous block (if any) should not
        # be detected as a gap
        self._t_prev = now
        self._last_event_pos = 0

    def _write_block(self, force_flush_map_file=False):
        if self._num_saved_filenames < len(self._filenames):
            self._update_log_sources_archive()
            self._num_saved_filenames = len(self._filenames)
        # pad with END opcodes (zeros)
        num_padding = self._max_bytecode_len - len(self._codes)
        self._codes.frombytes(bytes(2 * num_padding))
        self._map_block[0]['bytecode'] = np.frombuffer(self._codes, np.uint16)
        self._log_map_path.parent.mkdir(exist_ok=True)
        with self._log_map_path.open("ab") as f:
            f.write(self._map_block.tobytes())
            if force_flush_map_file:
                flush_map_file = True
            else:
                flush_map_file = (f.tell() == MAP_FILE_SIZE)
        if flush_map_file:
            # compress the map file
            with gzip.open(str(self._log_map_gz_path), 'wb') as f_w:
                f_w.write(self._log_map_path.read_bytes())
            self._log_map_path.unlink()
            # switch to next logmap file
            self._log_map_num += 1
        self._index_block[0]['min_stack_size'] = self._min_stack_size
        with self._log_index_path.open("ab") as f:
            f.write(self._index_block.tobytes())

    def _ensure_block_has_room(self, num_codes):
        if len(self._codes) + num_codes + BLOCK_RESERVE > self._max_bytecode_len:
            # not enough room, end the block with a timestamp taken
            # before writing it (this allows the analysis to exclude
            # the time spent writing the block), write it and start
            # a new block.
            self._codes.extend(self._encode_timestamp(time()))
            self._write_block()
            self._init_block()

    def _is_included(self, f_code):
        filename = f_code.co_filename
        if filename.startswith(TRACKEXEC_SRC_PREFIX):
            return False  # do not trace this trackexec recorder code
        if (f_code.co_name == "<module>" and
                filename not in self._module_level_files):
            return False  # do not trace module level loading code
        return (filename in self._include_files or
                filename.startswith(self._include_dirs))

    def _get_file_id(self, f_code):
        # note: we keep a reference to the code object in the cache,
        # otherwise its id could be reused by another code object
        # after it is garbage collected.
        cached = self._file_id_per_code_id.get(id(f_code))
        if cached is not None and cached[0] is f_code:
            return cached[1]
        else:
            # 1st time we see this f_code, check if we should trace it
            filename = f_code.co_filename
            if not self._is_included(f_code):
                file_id = -1
            else:
                # ok we will trace this code, check if we already found
                # this filename with another f_code
                file_id = self._id_per_filename.get(filename)
                if file_id is None:
                    # no, first time with this file
                    file_id = len(self._filenames)
                    self._filenames += [filename]
                    self._id_per_filename[filename] = file_id
                self._on_new_included_code(f_code)
            # in any case, record to avoid these checks next time
            self._file_id_per_code_id[id(f_code)] = (f_code, file_id)
        return file_id

    def _on_call(self, file_id):
        now = time()
        if now - self._t_prev > self._gap_threshold:
            self._record_gap(now)
        self._t_prev = now
        # if moving into the same file, preserve the current lineno as a
        # reference for possibly stripping out next LINE opcode; otherwise,
        # forget it.
        stack_file_ids = self._stack_file_ids
        if len(stack_file_ids) == 0 or stack_file_ids[-1] != file_id:
            self._current_lineno = LINENO_UNDEFINED
        self._ensure_block_has_room(2)
        codes = self._codes
        self._last_event_pos = len(codes)
        codes.append(OP_CALL)
        codes.append(file_id)
        stack_file_ids.append(file_id)
        self._stack_linenos.append(self._current_lineno)

    def _on_return(self):
        now = time()
        if now - self._t_prev > self._gap_threshold:
            self._record_gap(now)
        self._t_prev = now
        stack_file_ids = self._stack_file_ids
        if len(stack_file_ids) == 0:
            self._last_event_pos = len(self._codes)
            return  # unexpected, ignore
        # optimize:
        # 1. strip out "CALL <fileid>; RETURN;" sequences
        # 2. thanks to the management of _current_lineno, the fact we
        #    strip out repeated LINE opcodes, and optimization 1, we
        #    can also strip out the following pattern found with list
        #    comprehensions:
        #    [at line <F>:<N>]; CALL <F>; <N>; RETURN;
        codes = self._codes
        if len(codes) >= 2 and codes[-2] == OP_CALL:
            # strip out CALL RETURN sequence
            del codes[-2:]
            self._last_event_pos = len(codes)
        else:
            self._ensure_block_has_room(1)
            self._last_event_pos = len(self._codes)
            self._codes.append(OP_RETURN)
            # if returning to some location of the same file, preserve the
            # current lineno as a reference for possibly stripping out next
            # LINE opcode; otherwise, forget it.
            if (
                    len(stack_file_ids) < 2 or
                    stack_file_ids[-2] != stack_file_ids[-1]
               ):
                self._current_lineno = LINENO_UNDEFINED
        stack_file_ids.pop()
        self._stack_linenos.pop()
        if len(stack_file_ids) < self._min_stack_size:
            self._min_stack_size = len(stack_file_ids)

    def _on_line(self, lineno):
        now = time()
        if now - self._t_prev > self._gap_threshold:
            self._record_gap(now)
        self._t_prev = now
        if lineno == LINENO_UNDEFINED:
            self._last_event_pos = len(self._codes)
            return
        # record the line number, unless we remain on the same line,
        # in which case we strip out this new LINE opcode
        if lineno != self._current_lineno:
            self._ensure_block_has_room(1)
            self._last_event_pos = len(self._codes)
            self._codes.append(lineno)
            if len(self._stack_linenos) > 0:
                self._stack_linenos[-1] = lineno
            self._current_lineno = lineno
        else:
            self._last_event_pos = len(self._codes)

    def _record_gap(self, now):
        """The last event (and the instruction it started) took more than
        the gap threshold: enclose its codes with 2 timestamps, for the
        analysis to know its exact duration."""
        pos = self._last_event_pos
        if OP_TIMESTAMP in self._codes[pos:]:
            # safety check (should not happen): we cannot insert a
            # timestamp before another one, since timestamps are encoded
            # as offsets from the previous one.
            # note: no other code can be equal to OP_TIMESTAMP.
            return
        # note: the room for these 10 codes is reserved (BLOCK_RESERVE)
        self._codes[pos:pos] = array("H", self._encode_timestamp(self._t_prev))
        self._codes.extend(self._encode_timestamp(now))

    def _record_timestamp(self):
        self._ensure_block_has_room(5)
        self._codes.extend(self._encode_timestamp(time()))

    def _encode_timestamp(self, t):
        """Return the 5 codes encoding a timestamp (t is a value returned
        by time.time())"""
        # we ensure we record a monotonic suite of timestamps
        ts = int(t * SEC_AS_TS)
        if ts < self._last_timestamp:
            ts = self._last_timestamp
        # record an offset from the last timestamp, for lower values
        # and better compressability
        ts_offset = ts - self._last_timestamp
        self._last_timestamp = ts
        # encode the timestamp ensuring none of the four uint16 values
        # could match an opcode.
        return (OP_TIMESTAMP,
                (ts_offset & 0x7fff) + 1,
                ((ts_offset >> 15) & 0x7fff) + 1,
                ((ts_offset >> 30) & 0x7fff) + 1,
                ((ts_offset >> 45) & 0x7fff) + 1)


    def _stop(self):
        """Function for stopping and flushing"""
        self._disable()                                 # stop tracing
        self._record_timestamp()                        # record a final timestamp
        self._write_block(force_flush_map_file=True)    # flush

    @classmethod
    def start_recording(cls, calling_frame, *args, **kwargs):
        if TrackExecRecorder._instance is not None:
            raise RuntimeError("trackexec is already recording.")
        recorder_cls = _select_backend()
        instance = recorder_cls(*args, **kwargs)
        TrackExecRecorder._instance = instance
        try:
            # initialize the stack considering the calling code
            instance.start(calling_frame)
        except BaseException:
            instance._disable()
            TrackExecRecorder._instance = None
            raise

    @classmethod
    def stop(cls):
        instance = TrackExecRecorder._instance
        if instance is not None:
            TrackExecRecorder._instance = None
            instance._stop()

    @staticmethod
    def _after_fork_in_child():
        # the child process must not record anything in the trace
        # of its parent.
        instance = TrackExecRecorder._instance
        if instance is not None:
            TrackExecRecorder._instance = None
            instance._disable()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
            after_in_child=TrackExecRecorder._after_fork_in_child)


class SettraceRecorder(TrackExecRecorder):
    """Backend based on sys.settrace() (all python versions)"""

    def _enable_frame(self, frame):
        frame.f_trace = self._trace_local_function

    def _enable(self):
        sys.settrace(self._trace_call_function)

    def _disable(self):
        sys.settrace(None)

    def _trace_call_function(self, frame, event, arg):
        if self._pid != getpid():
            # this is the code of a forked child, bypass and disable
            # (needed when os.register_at_fork() is not available)
            sys.settrace(None)
            return
        file_id = self._get_file_id(frame.f_code)
        if file_id == -1:
            return
        self._on_call(file_id)
        return self._trace_local_function

    def _trace_local_function(self, frame, event, arg):
        if event == 'return':
            self._on_return()
        elif event == "line":
            self._on_line(frame.f_lineno)


class MonitoringRecorder(TrackExecRecorder):
    """Backend based on sys.monitoring (python >= 3.12).

    Compared to sys.settrace(), events of code which should not be
    recorded are disabled after their first occurrence, so this code
    runs (almost) at full speed.
    Only the thread which started the recording is recorded (as with
    sys.settrace(), which applies to the current thread only).
    """
    # ids proposed by sys.monitoring for profilers, then unassigned ones
    TOOL_IDS = (2, 3, 4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tool_id = None
        self._thread_id = get_ident()
        self._local_codes = []
        self._resume_lines = {}

    @classmethod
    def available(cls):
        return (hasattr(sys, "monitoring") and
                cls._find_free_tool_id() is not None)

    @classmethod
    def _find_free_tool_id(cls):
        for tool_id in cls.TOOL_IDS:
            if sys.monitoring.get_tool(tool_id) is None:
                return tool_id
        return None

    def _setup(self):
        mon = sys.monitoring
        E = mon.events
        tool_id = self._find_free_tool_id()
        if tool_id is None:
            raise RuntimeError("No free sys.monitoring tool id.")
        mon.use_tool_id(tool_id, "trackexec")
        self._tool_id = tool_id
        # events may have been disabled at some code locations
        # (by a previous recording session or by other tools);
        # re-enable them.
        mon.restart_events()
        for events, callback in (
                (E.PY_START, self._mon_start),
                (E.PY_RESUME, self._mon_resume),
                (E.PY_THROW, self._mon_throw),
                (E.PY_RETURN | E.PY_YIELD, self._mon_return),
                (E.PY_UNWIND, self._mon_unwind),
                (E.LINE, self._mon_line)):
            for event_id in range(events.bit_length()):
                if events & (1 << event_id):
                    mon.register_callback(tool_id, 1 << event_id, callback)

    def _enable_frame(self, frame):
        pass  # local events were set by _on_new_included_code()

    def _on_new_included_code(self, f_code):
        # we need LINE events for this code only
        sys.monitoring.set_local_events(
                self._tool_id, f_code, sys.monitoring.events.LINE)
        self._local_codes.append(f_code)

    def _enable(self):
        E = sys.monitoring.events
        sys.monitoring.set_events(self._tool_id,
                E.PY_START | E.PY_RESUME | E.PY_THROW |
                E.PY_RETURN | E.PY_YIELD | E.PY_UNWIND)

    def _disable(self):
        mon = sys.monitoring
        tool_id = self._tool_id
        if tool_id is None:
            return
        self._tool_id = None
        mon.set_events(tool_id, 0)
        for f_code in self._local_codes:
            mon.set_local_events(tool_id, f_code, 0)
        self._local_codes = []
        for event_id in range(mon.events.PY_UNWIND.bit_length()):
            mon.register_callback(tool_id, 1 << event_id, None)
        mon.free_tool_id(tool_id)

    # note about the callbacks below: returning sys.monitoring.DISABLE
    # disables the event at this code location; it must only be returned
    # for code we never record, since the event is disabled for all
    # threads.
    def _mon_start(self, f_code, instruction_offset):
        file_id = self._get_file_id(f_code)
        if file_id == -1:
            return sys.monitoring.DISABLE
        if get_ident() == self._thread_id:
            self._on_call(file_id)

    def _mon_resume(self, f_code, instruction_offset):
        file_id = self._get_file_id(f_code)
        if file_id == -1:
            return sys.monitoring.DISABLE
        if get_ident() == self._thread_id:
            self._on_call(file_id)
            # when a generator or coroutine is resumed on the same line
            # as the one where it was suspended, there is no LINE event.
            # Record this line anyway (as with sys.settrace()), otherwise
            # this call would be considered empty and stripped out.
            self._on_line(self._resume_line(f_code, instruction_offset))

    def _resume_line(self, f_code, instruction_offset):
        key = (f_code, instruction_offset)
        lineno = self._resume_lines.get(key)
        if lineno is None:
            lineno = LINENO_UNDEFINED
            for start, end, line in f_code.co_lines():
                if start <= instruction_offset < end:
                    if line is not None:
                        lineno = line
                    break
            self._resume_lines[key] = lineno
        return lineno

    def _mon_throw(self, f_code, instruction_offset, exception):
        # (PY_THROW events cannot be disabled)
        if get_ident() == self._thread_id:
            file_id = self._get_file_id(f_code)
            if file_id != -1:
                self._on_call(file_id)

    def _mon_return(self, f_code, instruction_offset, retval):
        if self._get_file_id(f_code) == -1:
            return sys.monitoring.DISABLE
        if get_ident() == self._thread_id:
            self._on_return()

    def _mon_unwind(self, f_code, instruction_offset, exception):
        # (PY_UNWIND events cannot be disabled)
        if get_ident() == self._thread_id:
            if self._get_file_id(f_code) != -1:
                self._on_return()

    def _mon_line(self, f_code, line_number):
        # (LINE events are only enabled on recorded code)
        if get_ident() == self._thread_id:
            self._on_line(line_number)


def _select_backend():
    backend = os.environ.get("TRACKEXEC_BACKEND", "auto")
    if backend == "settrace":
        return SettraceRecorder
    if backend == "monitoring":
        if not hasattr(sys, "monitoring"):
            raise RuntimeError(
                "TRACKEXEC_BACKEND=monitoring requires python >= 3.12.")
        return MonitoringRecorder
    if backend != "auto":
        raise RuntimeError(f"Invalid TRACKEXEC_BACKEND value: {backend}")
    if MonitoringRecorder.available():
        return MonitoringRecorder
    return SettraceRecorder
