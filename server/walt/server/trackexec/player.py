import bisect
import gzip
import pickle
import numba as nb
import numpy as np
import sys

from collections import defaultdict
from datetime import datetime, timedelta, date, time as midnight
from pathlib import Path
from plumbum import cli
from walt.doc.pager import Pager, SCROLL_HELP
from walt.server.trackexec.const import (
        OpCodes, MAP_BLOCK_ID_MASK, MAP_BLOCK_ID_SHIFT, MAP_BLOCK_UINT16_SIZE,
        SEC_AS_TS, MIN_AS_TS, HOUR_AS_TS, DAY_AS_TS
)
from walt.server.trackexec.tools import (
        Uint16Stack, map_block_dt, index_block_dt, LogAbstractManagement
)


# This function is called for each block when building the
# source index. There may be many blocks to read, depending
# on how long the process execution has been. For this reason,
# we use numba to accelerate this processing by several orders
# of magnitude.
@nb.jit(nopython=True)
def _fast_get_block_line_numbers(startup_stack, bytecode,
        op_call, op_return, op_end, op_timestamp):
    bytecode_pos = 0
    file_ids_stack = np.empty(MAP_BLOCK_UINT16_SIZE, np.uint16)
    file_ids_stack_pos = len(startup_stack)
    file_ids_stack[0:file_ids_stack_pos] = startup_stack
    results = np.empty(MAP_BLOCK_UINT16_SIZE, np.uint32)
    results_pos = 0
    while True:
        opcode = bytecode[bytecode_pos]
        bytecode_pos += 1
        if opcode == op_call:
            file_id = bytecode[bytecode_pos]
            bytecode_pos += 1
            file_ids_stack[file_ids_stack_pos] = file_id
            file_ids_stack_pos += 1
        elif opcode == op_return:
            file_ids_stack_pos -= 1
        elif opcode == op_end:
            break
        elif opcode == op_timestamp:
            bytecode_pos += 4
        else:  # opcode is a line number
            file_id = file_ids_stack[file_ids_stack_pos-1]
            results[results_pos] = (file_id << 16) + opcode
            results_pos += 1
    mask = (1<<16) -1
    results = np.unique(results[:results_pos])
    return (results >> 16), (results & mask)


class TrackExecPlayer(Pager, LogAbstractManagement):

    def __init__(self, dir_path):
        Pager.__init__(self)
        LogAbstractManagement.__init__(self, dir_path)
        self._filenames = []
        self._file_ids_stack = Uint16Stack()
        self._old_filename = None
        self._lineno = None
        self._filenames = list(self._log_sources_order_path.read_text().splitlines())
        self._block_id = 0
        self._index_blocks = np.memmap(self._log_index_path,
                                       dtype=index_block_dt(),
                                       mode='r')
        self._index_blocks_endtime = int(
                self._log_index_path.lstat().st_mtime * SEC_AS_TS)
        self._src_index = None
        self._map_blocks = None
        self._pending = ""
        self._bytecode = None
        self._timestamps_per_pos = None
        self._breakpoints = set()
        self._num_breakpoints_per_block_id = defaultdict(int)
        self._load_source_index()
        self._discard_block_data()
        self._block_id = 0
        self._read_block()
        self._update_scrolling = True

    def _discard_block_data(self):
        self._bytecode = None
        self._map_blocks = None

    def _load_source_index(self):
        # Even if the source index file exists, the trace may be longer now.
        # Let's point self._block_id to the first block not yet indexed.
        # Note: the source index file encodes a tuple of 2 values:
        # 1. the number of blocks encoded (= the next block_id to encode)
        # 2. a dictionary (<fild_id>,<lineno>) -> set(<block_ids>)
        if self._log_sources_index_gz_path.exists():
            with gzip.open(str(self._log_sources_index_gz_path), 'rb') as f_r:
                cache_content = f_r.read()
            self._block_id, self._src_index = pickle.loads(cache_content)
        else:
            self._block_id, self._src_index = (0, defaultdict(set))
        num_added_blocks = len(self._index_blocks) - self._block_id
        if num_added_blocks > 0:
            # Analyse blocks which were added to the trace.
            for block_id in self._browse_blocks():
                op_num = block_id + num_added_blocks + 1 - len(self._index_blocks)
                print(f"Updating source index... {op_num}/{num_added_blocks}\r", end="")
                self._read_block(compute_timestamps=False)
                file_ids, linenos = _fast_get_block_line_numbers(
                        self._file_ids_stack.view(), self._bytecode,
                        OpCodes.CALL, OpCodes.RETURN, OpCodes.END, OpCodes.TIMESTAMP)
                for file_id, lineno in zip(file_ids, linenos):
                    self._src_index[(file_id, lineno)].add(block_id)
            print()
            # Update the source index file
            cache_content = pickle.dumps((self._block_id, self._src_index))
            with gzip.open(str(self._log_sources_index_gz_path), 'wb') as f_w:
                f_w.write(cache_content)
            # reset current line number
            self._lineno = None

    def _toggle_breakpoint(self, lineno):
        bp = (self._file_id, lineno)
        if bp in self._breakpoints:
            self._breakpoints.discard(bp)
            for block_id in self._src_index[bp]:
                self._num_breakpoints_per_block_id[block_id] -= 1
        else:
            valid_line = False
            for block_id in self._src_index[bp]:
                valid_line = True
                self._num_breakpoints_per_block_id[block_id] += 1
            if valid_line:
                self._breakpoints.add(bp)
            else:
                self.error_message = (
                    "Invalid breakpoint position: "
                    f"line {lineno} not found in the exec trace"
                )
                return False
        return True

    @property
    def _filename(self):
        if len(self._file_ids_stack) == 0:
            return None
        else:
            return self._filenames[self._file_ids_stack.top()]

    @property
    def _file_id(self):
        if len(self._file_ids_stack) == 0:
            return None
        else:
            return self._file_ids_stack.top()

    @property
    def _state(self):
        """Save the player state"""
        return (self._file_ids_stack.copy(), self._lineno, self._old_filename,
                self._scroll_index, self._block_id, self._bytecode_pos)

    @_state.setter
    def _state(self, value):
        """Restore the player to previously saved state"""
        # read the block_id and load the block
        self._map_blocks = None
        self._block_id = value[4]
        self._read_block()
        # restore other state attributes
        (self._file_ids_stack, self._lineno, self._old_filename,
         self._scroll_index, self._block_id, self._bytecode_pos) = value

    def _bytecode_has_lineno(self, start_pos, end_pos):
        saved_bytecode_pos = self._bytecode_pos
        self._bytecode_pos = start_pos
        result = False
        for lineno in self._browse_block_line_numbers(preserve_state=True):
            if self._bytecode_pos < end_pos:
                result = True
            break
        self._bytecode_pos = saved_bytecode_pos
        return result

    def _is_last_block(self):
        return self._block_id == len(self._index_blocks) - 1

    def _is_start_of_trace(self):
        if self._block_id > 0:
            return False
        if self._bytecode_has_lineno(0, self._bytecode_pos):
            return False
        return True

    def _is_end_of_trace(self):
        if not self._is_last_block():
            return False
        if self._bytecode_has_lineno(self._bytecode_pos, len(self._bytecode)):
            return False
        return True

    def _read_block(self, compute_timestamps=True):
        if self._map_blocks is None:
            self._log_map_num = self._block_id >> MAP_BLOCK_ID_SHIFT
            if self._log_map_path.exists():
                map_bytes = self._log_map_path.read_bytes()
            elif self._log_map_gz_path.exists():
                with gzip.open(str(self._log_map_gz_path), 'rb') as f_r:
                    map_bytes = f_r.read()
            self._map_blocks = np.frombuffer(map_bytes, dtype=map_block_dt(1))
        map_block_id = self._block_id & MAP_BLOCK_ID_MASK
        block = self._map_blocks[map_block_id]
        stack_size = block['stack_size']
        block = self._map_blocks[map_block_id:map_block_id+1].view(
                        dtype=map_block_dt(stack_size))[0]
        self._file_ids_stack.copy_from(block['stack'])
        self._bytecode = block['bytecode']
        self._bytecode_pos = 0
        if compute_timestamps:
            self._compute_pos_timestamps()

    def _compute_pos_timestamps(self):
        ts_start, ts_end = self._get_block_ts_boundaries()
        timestamps = [(-1, ts_start)]
        last_timestamp = ts_start
        for pos in (self._bytecode == OpCodes.TIMESTAMP).nonzero()[0]:
            # decode the timestamp (was encoded in recorder.py)
            ts_offset = 0
            for n in self._bytecode[pos+4:pos:-1]:
                ts_offset <<= 15
                ts_offset += n - 1
            ts = last_timestamp + ts_offset
            timestamps.append((pos, ts))
            last_timestamp = ts
        timestamps.append((MAP_BLOCK_UINT16_SIZE, ts_end))
        self._timestamps_per_pos = {}
        for lineno in self._browse_block_line_numbers(preserve_state=True):
            pos = self._bytecode_pos - 1  # self._bytecode_pos is actually the next pos
            insert_pos = bisect.bisect_left(timestamps, (pos,))
            prev_pos, prev_ts = timestamps[insert_pos-1]
            next_pos, next_ts = timestamps[insert_pos]
            ts_offset = int(next_ts - prev_ts)
            ts_offset *= (pos - prev_pos)
            ts_offset /= (next_pos - prev_pos)
            ts = int(prev_ts + ts_offset)
            self._timestamps_per_pos[pos] = ts
        # restore this
        self._bytecode_pos = 0

    def _read_ushort(self):
        u = self._bytecode[self._bytecode_pos]
        self._bytecode_pos += 1
        return u

    def _pass_block_index_filter(self, block_index_filter):
        if block_index_filter is None:
            return True
        return block_index_filter(self._index_blocks[self._block_id])

    def _browse_block_line_numbers(self, preserve_state=False):
        if self._bytecode is None:
            self._read_block()
        while True:
            opcode = self._read_ushort()
            if opcode == OpCodes.CALL:
                file_id = self._read_ushort()
                if not preserve_state:
                    self._file_ids_stack.add(file_id)
            elif opcode == OpCodes.RETURN:
                if not preserve_state:
                    self._file_ids_stack.pop()
            elif opcode == OpCodes.END:
                return
            elif opcode == OpCodes.TIMESTAMP:
                self._bytecode_pos += 4
            else:  # opcode is a line number
                if not preserve_state:
                    self._lineno = opcode
                yield opcode

    def _browse_blocks(self):
        while True:
            if self._block_id >= len(self._index_blocks):
                return  # end of log trace
            yield self._block_id
            self._block_id += 1
            if self._block_id & MAP_BLOCK_ID_MASK == 0:
                # will need to read next map file
                self._map_blocks = None
            self._bytecode = None  # discard current block data

    def _block_has_breakpoints(self):
        return self._num_breakpoints_per_block_id[self._block_id] > 0

    def _step_file_and_lineno(self):
        for block_id in self._browse_blocks():
            for lineno in self._browse_block_line_numbers():
                # line opcode found
                return True
        self.error_message = """"step" failed: reached the end of exec trace"""
        return False

    def _next_file_and_lineno(self):
        init_stack_depth = len(self._file_ids_stack)
        for block_id in self._browse_blocks():
            if (
                self._index_blocks[block_id]['min_stack_size'] > init_stack_depth
                    and not self._block_has_breakpoints()
                    and not self._is_last_block()
               ):
                continue  # we can avoid analysing this block further
            for lineno in self._browse_block_line_numbers():
                # test if "next" operation terminates here
                if len(self._file_ids_stack) <= init_stack_depth:
                    return True
                # test if we should stop because of a breakpoint
                if (self._file_id, self._lineno) in self._breakpoints:
                    return True
                # test if we should stop because of reaching the end
                if self._is_end_of_trace():
                    return True
        self.error_message = """"next" failed: reached the end of exec trace"""
        return False

    def _continue(self):
        for block_id in self._browse_blocks():
            # when there is no breakpoint involved, "continue" should run
            # up to the end
            if self._is_last_block() or self._block_has_breakpoints():
                for lineno in self._browse_block_line_numbers():
                    # test if we should stop because of a breakpoint
                    if (self._file_id, self._lineno) in self._breakpoints:
                        return True
                    # test if we should stop because of reaching the end
                    if self._is_end_of_trace():
                        return True
        self.error_message = """"continue" failed: reached the end of exec trace"""
        return False

    def _jump(self, target_ts):
        # ts(blockN) < target_ts < ts(blockN+1) => use blockN
        self._block_id = np.searchsorted(self._index_blocks['timestamp'], target_ts) - 1
        if self._block_id < 0:
            self._block_id = 0
        # discard current block data
        self._map_blocks = None
        self._bytecode = None
        # find the line opcode just before the target timestamp
        last_state = None
        for lineno in self._browse_block_line_numbers():
            if last_state is not None and self._approximate_timestamp() > target_ts:
                break
            else:
                last_state = self._state
        # jump to this selected state
        self._state = last_state
        return True

    def get_md_content(self, rows, **env):
        if self._lineno is None:
            self._step_file_and_lineno()
        breakpoints = tuple(
                str(lineno) for (file_id, lineno) in self._breakpoints
                if file_id == self._file_id)
        code_flags = f"linenos highlight-line={self._lineno}"
        code_flags += " breakpoints=" + ",".join(breakpoints)
        source_text = (self._log_sources_path / self._filename).read_text()
        md_text = (f"""
```python3 {code_flags}
{source_text}```
""")
        if self._update_scrolling:
            # by default, we compute the index (scrolling position) to have
            # the highlighted line at one 5th of the screen (or upper if
            # targetting one of the first lines of the file).
            # if same file (only the line number changed),
            # check if we should really update this index, or if the old one
            # is still fine.
            scroll_index = max(0, self._lineno - (rows//5))
            if (
                    self._filename == self._old_filename and
                    self._lineno - self._scroll_index > 5 and
                    self._scroll_index + rows - self._lineno > 5
               ):
                # yes, the highlighted line would still be visible in the
                # current screen, so keep the old position
                scroll_index = self._scroll_index
            else:
                # update scrolling position
                self._scroll_index = scroll_index  # update for next call
        else:
            scroll_index = self._scroll_index   # keep scrolling position
        return md_text, scroll_index

    def _get_block_ts_boundaries(self):
        block_ts_start = self._index_blocks[self._block_id]['timestamp']
        if self._is_last_block():
            block_ts_end = self._index_blocks_endtime
        else:
            block_ts_end = self._index_blocks[self._block_id+1]['timestamp']
        return block_ts_start, block_ts_end

    def _approximate_timestamp(self):
        return self._timestamps_per_pos[self._bytecode_pos-1]

    def _timestamp_to_datetime(self, ts):
        return datetime.fromtimestamp(float(ts) / SEC_AS_TS)

    def get_header_text(self, cols, **env):
        location = f"{self._log_sources_path}/{self._filename}:{self._lineno}"
        location_maxlen = cols - len("location: ")
        if len(location) > location_maxlen:
            location = "..." + location[len(location)-location_maxlen+3:]
        ts = self._timestamp_to_datetime(self._approximate_timestamp()).isoformat(" ")
        if self._is_start_of_trace():
            flag = " [START OF TRACE]"
        elif self._is_end_of_trace():
            flag = " [END OF TRACE]"
        else:
            flag = ""
        return f"approx. time: {ts}{flag}\nlocation: {location}"

    def get_footer_help_keys(self, scrollable, **env):
        help_keys = (
            "<n>: next", "<s>: step", "<q>: quit", "<c>: continue",
            "<b>, <13b>, <56b>, ...: toggle breakpoints",
            "<+0.2s>, <-2d>, <2024-01-23@>, <14:52:07.10354@>...: jump in time"
        )
        if scrollable:
            help_keys += (SCROLL_HELP,)
        return help_keys

    def handle_keypress(self, c, **env):
        if c in "~":                # ignored chars
            return
        state = self._state  # save state
        command_chars = "bcdhmnqs@"  # these chars mark the end of a command
        esc_command_chars = "AB56"   # these chars mark the end of an esc command
        other_chars = "+-\x1b[01234789.:"
        self.error_message = None  # init
        invalid_command = False
        self._pending += c
        cmd = self._pending
        if c not in (command_chars + esc_command_chars + other_chars):
            invalid_command = True
        elif cmd[:2] == "\x1b[":
            if len(cmd) > 2:
                self._pending = ""   # next chars should start from an empty buffer
                if c == "A":  # up   (we get '\x1b[A')
                    return Pager.SCROLL_UP
                elif c == "B":  # down
                    return Pager.SCROLL_DOWN
                elif c == "5":  # up
                    return Pager.SCROLL_PAGE_UP
                elif c == "6":  # down
                    return Pager.SCROLL_PAGE_DOWN
        elif c in command_chars:
            self._pending = ""   # next chars should start from an empty buffer
            if cmd[0] in "+-":
                if c in "dhms":
                    try:
                        offset = float(cmd[:-1])
                    except Exception:
                        invalid_command = True
                    if not invalid_command:
                        offset *= {
                                "s": SEC_AS_TS,
                                "m": MIN_AS_TS,
                                "h": HOUR_AS_TS,
                                "d": DAY_AS_TS,
                        }[c]
                        if self._jump(self._approximate_timestamp() + offset):
                            self._update_scrolling = True
                            return Pager.UPDATE_MD_CONTENT_NO_RETURN
                        else:
                            self._state = state   # restore previous state
            elif cmd[-1] == "@":
                curr_ts = self._approximate_timestamp()
                curr_unix_ts = curr_ts / SEC_AS_TS
                try:
                    if ':' in cmd:
                        h, m, s = cmd[:-1].split(':')
                        h, m, s = int(h), int(m), float(s)
                        curr_date = date.fromtimestamp(curr_unix_ts)
                        dt = datetime.combine(curr_date, midnight())
                        dt += timedelta(hours=h, minutes=m, seconds=s)
                    else:
                        y, m, d = cmd[:-1].split('-')
                        y, m, d = int(y), int(m), int(d)
                        curr_time = datetime.fromtimestamp(curr_unix_ts).time()
                        selected_date = date(year=y, month=m, day=d)
                        dt = datetime.combine(selected_date, curr_time)
                    ts = int(dt.timestamp() * SEC_AS_TS)
                except Exception:
                    invalid_command = True
                if not invalid_command:
                    if self._jump(ts):
                        self._update_scrolling = True
                        return Pager.UPDATE_MD_CONTENT_NO_RETURN
                    else:
                        self._state = state   # restore previous state
            elif cmd == "q":
                return Pager.QUIT
            elif cmd == "b":
                if self._toggle_breakpoint(self._lineno):
                    self._update_scrolling = False
                    return Pager.UPDATE_MD_CONTENT_NO_RETURN
            elif cmd[-1] == "b":
                try:
                    lineno = int(cmd[:-1])
                except Exception:
                    invalid_command = True
                if lineno < 1:
                    invalid_command = True
                if not invalid_command:
                    if self._toggle_breakpoint(lineno):
                        self._update_scrolling = False
                        return Pager.UPDATE_MD_CONTENT_NO_RETURN
            elif cmd == "n":
                self._old_filename = self._filename
                if self._next_file_and_lineno():
                    self._update_scrolling = True
                    return Pager.UPDATE_MD_CONTENT_NO_RETURN
                else:
                    self._state = state   # restore previous state
            elif cmd == "s":
                self._old_filename = self._filename
                if self._step_file_and_lineno():
                    self._update_scrolling = True
                    return Pager.UPDATE_MD_CONTENT_NO_RETURN
                else:
                    self._state = state   # restore previous state
            elif cmd == "c":
                self._old_filename = self._filename
                if self._continue():
                    self._update_scrolling = True
                    return Pager.UPDATE_MD_CONTENT_NO_RETURN
                else:
                    self._state = state   # restore previous state
            else:
                invalid_command = True
        if invalid_command:
            self.error_message = f"Invalid command: {repr(cmd)}"
            self._pending = ""  # reset
        if self.error_message is not None:
            self._update_scrolling = False
            return Pager.UPDATE_MD_CONTENT_NO_RETURN

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
    return p


class TrackExecPlayerCli(cli.Application):
    def main(self, trackexec_log_dir : TrackExecLogDir):
        """Replay WalT server process execution logs"""
        TrackExecPlayer.replay(trackexec_log_dir)
        sys.exit(1)


def run():
    TrackExecPlayerCli.run()
