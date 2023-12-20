import numpy as np
import os
import sys

from pathlib import Path
from plumbum import cli
from walt.doc.pager import Pager
from walt.server.trackexec.const import BLOCK_SIZE, OpCodes
from walt.server.trackexec.tools import Uint16Stack, block_dt

DEBUG = False


class TrackExecPlayer(Pager):

    def __init__(self, dir_path):
        super().__init__("qn")
        self._filenames = []
        self._file_ids_stack = Uint16Stack()
        self._filename = None
        self._lineno = None
        self._old_index = None
        filenames = list((dir_path / "log_index").read_text().splitlines())
        self._prefix = filenames[0]
        self._filenames = filenames[1:]
        self._readpos = 0
        self._log_map_path = dir_path / "log_map"
        with self._log_map_path.open("rb") as f:
            self._endpos = f.seek(0, os.SEEK_END)
        self._read_block()
        if DEBUG:
            self._debug = open("/tmp/debug", "w")

    def _read_block(self):
        if self._readpos == self._endpos:
            sys.exit(0)  # end of file
        with self._log_map_path.open("rb") as f:
            # seek and load block
            f.seek(self._readpos, os.SEEK_SET)
            block = np.frombuffer(f.read(BLOCK_SIZE), dtype=block_dt(1))
            stack_size = block[0]['stack_size']
            block = block.view(dtype=block_dt(stack_size))
            self._file_ids_stack.copy_from(block[0]['stack'])
            self._bytecode = block[0]['bytecode']
            self._bytecode_pos = 0

    def _read_ushort(self):
        u = self._bytecode[self._bytecode_pos]
        self._bytecode_pos += 1
        return u

    def _next_file_and_lineno(self):
        while True:
            opcode = self._read_ushort()
            if opcode == OpCodes.END:
                self._readpos += BLOCK_SIZE
                self._read_block()
            elif opcode == OpCodes.CALL:
                file_id = self._read_ushort()
                self._file_ids_stack.add(file_id)
                self._filename = self._filenames[self._file_ids_stack.top()]
                if DEBUG:
                    self._debug.write(f"CALL {self._filename}\n")
                    self._debug.flush()
            elif opcode == OpCodes.RETURN:
                if DEBUG:
                    self._debug.write(f"RETURN FROM {self._filename}\n")
                    self._debug.flush()
                self._file_ids_stack.pop()
                self._filename = self._filenames[self._file_ids_stack.top()]
            else:
                self._lineno = opcode
                if DEBUG:
                    self._debug.write(f"LINE {self._lineno}\n")
                    self._debug.flush()
                return

    def get_md_content(self, rows, **env):
        old_filename = self._filename
        self._next_file_and_lineno()
        with open(f"{self._prefix}/{self._filename}", 'r') as source_file:
            source_text = source_file.read()
        md_text = (f"""
```python3 highlight-line={self._lineno}
{source_text}```
""")
        # by default, we compute the index (scrolling position) to have
        # the highlighted line at one third of the screen (or upper if
        # targetting one of the first lines of the file).
        # if same file (only the line number changed),
        # check if we should really update this index, or if the old one
        # is still fine.
        index = max(0, self._lineno - (rows//3))
        if (
                self._filename == old_filename and
                self._lineno - self._old_index > 7 and
                self._old_index + rows - self._lineno > 7
           ):
            # yes, the highlighted line would still be around the middle
            # of the screen, so keep the old position
            index = self._old_index
        else:
            # update scrolling position
            if DEBUG:
                self._debug.write(
                        f"SCROLL {self._filename} {self._old_index}->{index}\n")
                self._debug.flush()
            self._old_index = index  # update for next call
        return md_text, index

    def get_header_text(self, cols, **env):
        location = f"{self._prefix}/{self._filename}:{self._lineno}"
        if len(location) > cols:
            location = "..." + location[len(location)-cols+3:]
        return location

    def get_footer_help_keys(self, **env):
        return ("<n>: next", "<q>: quit")

    def handle_next(self, **env):
        pass    # just continue

    @classmethod
    def replay(cls, log_file):
        player = cls(log_file)
        player.start_display()


def _usage_error(tip):
    print(tip)
    sys.exit(1)


def TrackExecLogDir(s):
    p = Path(s)
    if not p.exists():
        _usage_error(f"No such directory: {s}")
    if not p.is_dir():
        _usage_error(f"Not a directory: {s}")
    if not (p / "log_index").exists():
        _usage_error('The specified directory must contain a "log_index" file.')


class TrackExecPlayerCli(cli.Application):
    def main(self, trackexec_log_dir : TrackExecLogDir):
        """Replay WalT server process execution logs"""
        TrackExecPlayer.replay(Path(trackexec_log_dir))
        sys.exit(1)


def run():
    TrackExecPlayerCli.run()
