import numpy as np
import sys

from datetime import datetime
from os import getpid
from time import time
from walt.server.trackexec.const import OpCodes
from walt.server.trackexec.tools import Uint16Stack, block_dt


class TrackExecRecorder:

    def __init__(self, package, dir_path, thread_name):
        pid = getpid()
        str_now = datetime.now().strftime("%y%m%d-%H%M")
        dir_path = dir_path / str_now / f"{thread_name}-{pid}"
        dir_path.mkdir(parents=True, exist_ok=True)
        self._prefix = package.__path__[0] + '/'
        self._filenames = []
        self._id_per_filename = {}
        self._file_ids_stack = Uint16Stack()
        self._bytecode = Uint16Stack()
        self._old_line = None
        self._log_index_path = dir_path / "log_index"
        with self._log_index_path.open("w") as f:
            f.write(package.__path__[0] + "\n")
        self._log_map_path = dir_path / "log_map"
        self._block = np.zeros(1, dtype=block_dt(0))
        self._init_block()

    def _register_filename(self, filename):
        with self._log_index_path.open("a") as f:
            f.write(filename + "\n")

    def _init_block(self):
        stack_size = self._file_ids_stack.level
        self._block = self._block.view(dtype=block_dt(stack_size))
        bl_content = self._block[0]
        bl_content['timestamp'] = int(time() * 1048576)
        bl_content['stack_size'] = stack_size
        bl_content['stack'] = self._file_ids_stack.view()
        self._max_bytecode_len = len(bl_content['bytecode'])
        self._bytecode.reset()

    def _write_block(self):
        self._bytecode.pad(OpCodes.END, self._max_bytecode_len)
        self._block[0]['bytecode'] = self._bytecode.view()
        with self._log_map_path.open("ab") as f:
            f.write(self._block.tobytes())

    def _ensure_block_has_room(self, num_codes):
        # note: we need room for padding at least 1 END marker
        if self._bytecode.level + num_codes + 1 > self._max_bytecode_len:
            # not enough room, write current block
            self._write_block()
            self._init_block()

    def _trace_function(self, frame, event, arg):
        try:
            return self._try_trace_function(frame, event, arg)
        except Exception as e:
            print(e)
            sys.exit()

    def _try_trace_function(self, frame, event, arg):
        if event == "call":
            filename = frame.f_code.co_filename
            # print(filename)
            if not filename.startswith(self._prefix):
                return  # only trace our own code
            if frame.f_code.co_name == "<module>":
                return  # do not trace module level loading code
            # print(frame.f_code)
            filename = filename[len(self._prefix):]
            if self._file_ids_stack.level > 0:
                old_file_id = self._file_ids_stack.top()
                old_filename = self._filenames[old_file_id]
                same_file = (old_filename == filename)
            else:
                same_file = False
            if same_file:
                file_id = old_file_id
            else:
                file_id = self._id_per_filename.get(filename)
                if file_id is None:
                    file_id = len(self._filenames)
                    self._filenames += [filename]
                    self._id_per_filename[filename] = file_id
                    self._register_filename(filename)
                self._ensure_block_has_room(2)
                self._bytecode.add(OpCodes.CALL)
                self._bytecode.add(file_id)
            self._file_ids_stack.add(file_id)
            return self._trace_function
        elif event == 'return':
            if self._file_ids_stack.level >= 2:
                same_file = (self._file_ids_stack[-1] == self._file_ids_stack[-2])
            else:
                same_file = False
            if not same_file:
                self._ensure_block_has_room(1)
                self._bytecode.add(OpCodes.RETURN)
            self._old_line = None
            self._file_ids_stack.pop()
        elif event == "line":
            lineno = frame.f_lineno
            if lineno != self._old_line:
                self._ensure_block_has_room(1)
                self._bytecode.add(lineno)
                self._old_line = lineno

    @classmethod
    def record(cls, *args):
        recorder = cls(*args)
        sys.settrace(recorder._trace_function)
