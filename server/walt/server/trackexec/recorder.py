import gzip
import numpy as np
import sys
import tarfile

from contextlib import nullcontext
from os import getpid
from os.path import dirname
from pathlib import Path
from time import time
from walt.server.trackexec.const import (
        OpCodes, MAP_FILE_SIZE, SEC_AS_TS, MAP_BLOCK_UINT16_SIZE
)
from walt.server.trackexec.tools import (
        Uint16Stack, map_block_dt, index_block_dt,
        LogAbstractManagement
)

TRACKEXEC_SRC_PREFIX = dirname(__file__) + "/"
LINENO_UNDEFINED = 0  # undefined (real linenos start at 1)


class TrackExecRecorder(LogAbstractManagement):
    _instance = None

    def __init__(self, mod_or_package, dir_path):
        super().__init__(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)
        if hasattr(mod_or_package, "__path__"):
            self._prefix = mod_or_package.__path__[0] + '/'
            self._module_file = None
        else:
            self._prefix = None
            self._module_file = mod_or_package.__file__
        self._filenames = []
        self._num_saved_filenames = 0
        self._file_id_per_code_id = {}
        self._id_per_filename = {}
        self._stack = np.empty(MAP_BLOCK_UINT16_SIZE,
                np.dtype([('file_id', np.uint16), ('lineno', np.uint16)]))
        self._stack_size = 0
        self._bytecode = Uint16Stack()
        self._map_block = np.zeros(1, dtype=map_block_dt(0))
        self._index_block = np.zeros(1, dtype=index_block_dt())
        self._last_timestamp = None
        self._timestamp_requested = False
        self._pt_section = False   # precise-timestamping sections
        self._pid = getpid()
        self._current_lineno = LINENO_UNDEFINED
        (dir_path / "pid").write_text(f"{self._pid}\n")

    def _recursive_call_stack_init(self, frame):
        # recurse first (register bottom calls of the stack first)
        if frame.f_back is not None:
            self._recursive_call_stack_init(frame.f_back)
        # unless filtered out, add the frame to the call stack
        # and enable tracing on it
        file_id = self._get_file_id(frame)
        if file_id != -1:
            self._stack[self._stack_size] = (file_id, frame.f_lineno)
            self._stack_size += 1
            frame.f_trace = self._trace_local_function
            self._current_lineno = frame.f_lineno

    def start(self, calling_frame):
        # when the recorder code is started, we analyse which frames of
        # the call stack match our filtering prefix; those frames are
        # used to initialize our call stack (self._stack) and we manually
        # enable tracing on them (by setting their 'f_trace' attribute),
        # in order to capture their execution when this code returns to
        # its caller.
        self._recursive_call_stack_init(calling_frame)
        self._init_block()
        # enable our trace function for next calls
        sys.settrace(self._trace_call_function)

    def _update_log_sources_archive(self):
        with tarfile.open(self._log_sources_archive_path, "w:gz") as t_w:
            for filename in self._filenames:
                t_w.add(filename)

    def _init_block(self):
        # update the log_index file
        stack_size = self._stack_size
        # we ensure we record a monotonic suite of timestamps
        ts = int(time() * SEC_AS_TS)
        if self._last_timestamp is None or ts > self._last_timestamp:
            self._last_timestamp = ts
        self._index_block[0]['timestamp'] = self._last_timestamp
        self._min_stack_size = stack_size
        self._map_block = self._map_block.view(dtype=map_block_dt(stack_size))
        bl_content = self._map_block[0]
        bl_content['stack_size'] = stack_size
        bl_content['stack'] = self._stack[:stack_size]
        self._max_bytecode_len = len(bl_content['bytecode'])
        self._bytecode.reset()

    def _write_block(self, force_flush_map_file=False):
        if self._num_saved_filenames < len(self._filenames):
            self._update_log_sources_archive()
            self._num_saved_filenames = len(self._filenames)
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

    def _get_file_id(self, frame):
        f_code = frame.f_code
        file_id = self._file_id_per_code_id.get(id(f_code))
        if file_id is None:
            # 1st time we see this f_code, check if we should trace it
            filename = f_code.co_filename
            if filename.startswith(TRACKEXEC_SRC_PREFIX):
                file_id = -1  # do not trace this trackexec recorder code
            elif f_code.co_name == "<module>":
                file_id = -1  # do not trace module level loading code
            elif self._prefix is None and filename != self._module_file:
                file_id = -1  # module mode, and entering another module
            elif self._prefix is not None and not filename.startswith(self._prefix):
                file_id = -1  # package mode, and entering external code
            else:
                # ok we will trace this code, check if we already found
                # this filename with another f_code
                file_id = self._id_per_filename.get(filename)
                if file_id is None:
                    # no, first time with this file
                    file_id = len(self._filenames)
                    self._filenames += [filename]
                    self._id_per_filename[filename] = file_id
            # in any case, record to avoid these checks next time
            self._file_id_per_code_id[id(f_code)] = file_id
        return file_id

    def _trace_call_function(self, frame, event, arg):
        if self._pid != getpid():
            # this is the code of a forked child, bypass and disable
            sys.settrace(None)
            return
        file_id = self._get_file_id(frame)
        if file_id == -1:
            return
        # if moving into the same file, preserve the current lineno as a
        # reference for possibly stripping out next LINE opcode; otherwise,
        # forget it.
        if (
                self._stack_size == 0 or
                self._stack[self._stack_size-1]["file_id"] != file_id
           ):
            self._current_lineno = LINENO_UNDEFINED
        self._ensure_block_has_room(2)
        self._bytecode.add(OpCodes.CALL)
        self._bytecode.add(file_id)
        self._stack[self._stack_size] = (file_id, self._current_lineno)
        self._stack_size += 1
        return self._trace_local_function

    def _trace_local_function(self, frame, event, arg):
        if event == 'return':
            # optimize:
            # 1. strip out "CALL <fileid>; RETURN;" sequences
            # 2. thanks to the management of _current_lineno, the fact we
            #    strip out repeated LINE opcodes, and optimization 1, we
            #    can also strip out the following pattern found with list
            #    comprehensions:
            #    [at line <F>:<N>]; CALL <F>; <N>; RETURN;
            bytecode = self._bytecode.view()
            if len(bytecode) >= 2 and bytecode[-2] == OpCodes.CALL:
                # strip out CALL RETURN sequence
                self._bytecode.pop()
                self._bytecode.pop()
            else:
                self._ensure_block_has_room(1)
                self._bytecode.add(OpCodes.RETURN)
                # if returning to some location of the same file, preserve the
                # current lineno as a reference for possibly stripping out next
                # LINE opcode; otherwise, forget it.
                top_of_stack = self._stack[:self._stack_size][-2:]
                if (
                        len(top_of_stack) < 2 or
                        top_of_stack[0]["file_id"] != top_of_stack[1]["file_id"]
                   ):
                    self._current_lineno = LINENO_UNDEFINED
            self._stack_size -= 1
            self._min_stack_size = min(
                self._min_stack_size,
                self._stack_size
            )
        elif event == "line":
            # if traversing a precise timestamping section,
            # record the timestamp of each instruction
            if self._pt_section or self._timestamp_requested:
                self._record_timestamp()
                self._timestamp_requested = False
            # record the line number, unless we remain on the same line,
            # in which case we strip out this new LINE opcode
            lineno = frame.f_lineno
            if lineno != self._current_lineno:
                self._ensure_block_has_room(1)
                self._bytecode.add(lineno)
                self._stack[self._stack_size-1]["lineno"] = lineno
                self._current_lineno = lineno

    def _record_timestamp(self):
        self._ensure_block_has_room(5)
        self._bytecode.add(OpCodes.TIMESTAMP)
        # we ensure we record a monotonic suite of timestamps
        ts = int(time() * SEC_AS_TS)
        if ts < self._last_timestamp:
            ts = self._last_timestamp
        # record an offset from the last timestamp, for lower values
        # and better compressability
        ts_offset = ts - self._last_timestamp
        # encode the timestamp ensuring none of the four uint16 values
        # could match an opcode.
        saved_ts_offset = ts_offset
        for _ in range(4):
            self._bytecode.add((ts_offset & 0x7fff)+1)
            ts_offset >>= 15
        self._last_timestamp = ts

    def __enter__(self):
        """PT section start boundary function"""
        self._pt_section = True

    def __exit__(self, *args):
        """PT section end boundary function"""
        # record a last timestamp to know how much time the last
        # instruction of the context took
        self._timestamp_requested = True
        self._pt_section = False

    def _stop(self):
        """Function for stopping and flushing"""
        sys.settrace(None)                              # stop tracing
        self._record_timestamp()                        # record a final timestamp
        self._write_block(force_flush_map_file=True)    # flush

    @classmethod
    def record(cls, *args):
        assert cls._instance is None
        cls._instance = cls(*args)
        # initialize the stack considering the calling code
        cls._instance.start(sys._getframe().f_back)

    @classmethod
    def precise_timestamping(cls):
        if cls._instance is not None:
            return cls._instance
        else:
            return nullcontext()

    @classmethod
    def stop(cls):
        if cls._instance is not None:
            cls._instance._stop()
            cls._instance = None
