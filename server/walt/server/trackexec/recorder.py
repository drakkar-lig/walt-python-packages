import gzip
import numpy as np
import sys

from os import getpid
from pathlib import Path
from time import time
from walt.server.trackexec.const import (
        OpCodes, MAP_FILE_SIZE, SEC_AS_TS
)
from walt.server.trackexec.tools import (
        Uint16Stack, map_block_dt, index_block_dt,
        LogAbstractManagement
)


class IdlePeriod:
    NONE = 0
    PENDING_IDLE_INSTRUCTION = 1
    PENDING_IDLE_END = 2


class TrackExecRecorder(LogAbstractManagement):
    _instance = None

    def __init__(self, package, dir_path):
        super().__init__(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)
        self._prefix = package.__path__[0] + '/'
        self._filenames = []
        self._id_per_filename = {}
        self._file_ids_stack = Uint16Stack()
        self._bytecode = Uint16Stack()
        self._old_line = None
        self._log_sources_path.mkdir()
        self._map_block = np.zeros(1, dtype=map_block_dt(0))
        self._index_block = np.zeros(1, dtype=index_block_dt())
        self._last_timestamp = None
        self._idle_period = IdlePeriod.NONE
        self._pid = getpid()
        (dir_path / "pid").write_text(f"{self._pid}\n")

    def _recursive_call_stack_init(self, frame):
        # recurse first (register bottom calls of the stack first)
        if frame.f_back is not None:
            self._recursive_call_stack_init(frame.f_back)
        # enable tracing of this frame (or not, if None is returned)
        frame.f_trace = self._trace_function(frame, "call", None)

    def start(self, calling_frame):
        self._init_block()
        # when the recorder code is started, we analyse which frames of
        # the call stack match our filtering prefix; those frames are
        # used to initialize our call stack (self._file_ids_stack) and
        # we manually enable tracing on them (by setting their 'f_trace'
        # attribute), in order to capture their execution when this code
        # returns to its caller.
        self._recursive_call_stack_init(calling_frame)
        # enable our trace function for next calls
        sys.settrace(self._trace_function)

    def _register_filename(self, filename):
        src = Path(self._prefix + filename)
        dst = self._log_sources_path / filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        with self._log_sources_order_path.open("a") as f:
            f.write(filename + "\n")

    def _init_block(self):
        # update the log_index file
        stack_size = self._file_ids_stack.level
        self._last_timestamp = int(time() * SEC_AS_TS)
        self._index_block[0]['timestamp'] = self._last_timestamp
        self._min_stack_size = stack_size
        self._map_block = self._map_block.view(dtype=map_block_dt(stack_size))
        bl_content = self._map_block[0]
        bl_content['stack_size'] = stack_size
        bl_content['stack'] = self._file_ids_stack.view()
        self._max_bytecode_len = len(bl_content['bytecode'])
        self._bytecode.reset()

    def _write_block(self, force_flush_map_file=False):
        self._bytecode.pad(OpCodes.END, self._max_bytecode_len)
        self._map_block[0]['bytecode'] = self._bytecode.view()
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
        # note: we need room for padding at least 1 END marker
        if self._bytecode.level + num_codes + 1 > self._max_bytecode_len:
            # not enough room, write current block
            self._write_block()
            self._init_block()

    def _trace_function(self, frame, event, arg):
        if event == "call":
            filename = frame.f_code.co_filename
            if not filename.startswith(self._prefix):
                return  # only trace our own code
            if filename == __file__:
                return  # avoid this trackexec recorder code too
            if frame.f_code.co_name == "<module>":
                return  # do not trace module level loading code
            if self._pid != getpid():
                return  # this is the code of a forked child, bypass
            filename = filename[len(self._prefix):]
            file_id = self._id_per_filename.get(filename)
            if file_id is None:
                file_id = len(self._filenames)
                self._filenames += [filename]
                self._id_per_filename[filename] = file_id
                self._register_filename(filename)
            elif self._file_ids_stack.top() != file_id:
                self._old_line = None
            self._ensure_block_has_room(2)
            self._bytecode.add(OpCodes.CALL)
            self._bytecode.add(file_id)
            self._file_ids_stack.add(file_id)
            return self._trace_function
        elif event == 'return':
            # optimize:
            # 1. strip out "CALL <fileid>; RETURN;" sequences
            # 2. thanks to the management of self._old_line we also strip out
            #    repeated <line> opcodes, which, combined with optimization 1,
            #    allows to strip out the following pattern found with
            #    list comprehensions:
            #    [at line <F>:<N>]; CALL <F>; <N>; RETURN;
            bytecode = self._bytecode.view()
            if len(bytecode) >= 2 and bytecode[-2] == OpCodes.CALL:
                self._bytecode.pop()
                self._bytecode.pop()
            else:
                self._ensure_block_has_room(1)
                self._bytecode.add(OpCodes.RETURN)
                self._old_line = None
            self._file_ids_stack.pop()
            self._min_stack_size = min(
                self._min_stack_size,
                self._file_ids_stack.level
            )
        elif event == "line":
            # idle period management:
            # considering the idle period is made of the instruction I,
            # we want to write the following bytecode
            # <lineno-of-I><ts-before-running-I><ts-after-running-I><next-lineno>
            # this way, <lineno-of-I> will be associated to a timestamp
            # very close to <ts-before-running-I>, and <next-lineno> to
            # a timestamp very close to <ts-after-running-I>, reflecting
            # the fact instruction I took a long delay to complete.
            # code section --A-- takes care of recording <ts-after-running-I>.
            # code section --B-- records instruction lines such as <lineno-of-I>,
            # <next-lineno>, and others not related to idle periods.
            # code section --C-- takes care of recording <ts-before-running-I>.
            #
            # section --A--
            if self._idle_period == IdlePeriod.PENDING_IDLE_END:
                self._record_timestamp()
                self._idle_period = IdlePeriod.NONE
            # section --B--
            lineno = frame.f_lineno
            if lineno != self._old_line:
                self._ensure_block_has_room(1)
                self._bytecode.add(lineno)
                self._old_line = lineno
            # section --C--
            if self._idle_period == IdlePeriod.PENDING_IDLE_INSTRUCTION:
                self._record_timestamp()
                self._idle_period = IdlePeriod.PENDING_IDLE_END

    def _record_timestamp(self):
        self._ensure_block_has_room(5)
        self._bytecode.add(OpCodes.TIMESTAMP)
        # record an offset from the last timestamp, for lower values
        # and better compressability
        ts = int(time() * SEC_AS_TS)
        ts_offset = ts - self._last_timestamp
        self._last_timestamp = ts
        # encode the timestamp ensuring none of the four uint16 values
        # could match an opcode.
        for _ in range(4):
            self._bytecode.add((ts_offset & 0x7fff)+1)
            ts_offset >>= 15

    def __enter__(self):
        """Idle period start boundary function"""
        self._idle_period = IdlePeriod.PENDING_IDLE_INSTRUCTION
        return self

    def __exit__(self, *args):
        """Idle period end boundary function"""
        pass

    def _stop(self):
        """Function for stopping and flushing"""
        sys.settrace(None)                              # stop tracing
        self._write_block(force_flush_map_file=True)    # flush

    @classmethod
    def record(cls, *args):
        assert cls._instance is None
        cls._instance = cls(*args)
        # initialize the stack considering the calling code
        cls._instance.start(sys._getframe().f_back)

    @classmethod
    def idle_period_recorder(cls):
        if cls._instance is not None:
            return cls._instance

    @classmethod
    def stop(cls):
        if cls._instance is not None:
            cls._instance._stop()
            cls._instance = None
