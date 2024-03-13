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


MD_HELP_SCREEN = """
Shortcut keys:
* <q>: quit
* <h>: toggle this help screen
* <n>/<s>/<c>: next/step/continue like in a debugger

Scrolling in source files:
* Use arrow keys or page-up / page-down.

Other keys start a full-line command prompt.
Sample full-line commands:
```bash
> b                     # toggle breakpoint at current line
> b 12                  # toggle breakpoint at line 12
> j 12:00:16.552353     # jump to selected time
> j 2024-01-27          # jump to selected date (for long-running programs)
> j +2s                 # fast-forward 2 seconds
> j +0.003s             # fast-forward 3 milliseconds
> j -3m                 # fast-rewind 3 minutes
> j +1h                 # fast-forward 1 hour
> j -15d                # fast-rewind 15 days
> f uniquemod.py        # display file <somewhere>/uniquemod.py
> f /mod/submod.py      # display file <somewhere>/mod/submod.py
```

Jumps in time (`j` command) select the last instruction before the exact \
target time.
By default, the file displayed reflects the current execution replay
section. But using `f` command one may display another file, set
breakpoints on it using `b <line>`, and then press `<c>` (i.e., continue)
to fast-forward to one of these breakpoints.

Press <h> again to leave this help screen.
"""


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
        self._old_display_filename = None
        self._lineno = None
        self._filenames = list(self._log_sources_order_path.read_text().splitlines())
        self._block_id = 0
        self._index_blocks = np.memmap(self._log_index_path,
                                       dtype=index_block_dt(),
                                       mode='r')
        self._src_index = None
        self._map_blocks = None
        self._pending = ""
        self._bytecode = None
        self._timestamps_per_pos = None
        self._breakpoints = set()
        self._num_breakpoints_per_block_id = defaultdict(int)
        self._endtime = self._init_compute_endtime()
        self._init_load_source_index()
        # start with block 0
        self._block_id = 0
        self._read_block()
        self._update_scrolling = True
        self._help_screen = False
        self._explicit_display_file_id = None

    def _init_compute_endtime(self):
        # compute self._endtime by reading timestamps of the last block
        self._block_id = len(self._index_blocks) -1
        self._read_block(compute_timestamps=False)
        block_ts_start = self._index_blocks[self._block_id]['timestamp']
        last_ts = None
        for pos, ts in self._iterate_block_pos_timestamps(block_ts_start):
            last_ts = ts
        self._discard_block_data()  # cleanup
        return last_ts

    def _discard_block_data(self):
        self._bytecode = None
        self._map_blocks = None

    def _init_load_source_index(self):
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
        self._discard_block_data()  # cleanup

    def _toggle_breakpoint(self, lineno):
        bp = (self._display_file_id, lineno)
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
    def _display_filename(self):
        return self._filenames[self._display_file_id]

    @property
    def _exec_file_id(self):
        return self._file_ids_stack.top()

    @property
    def _display_file_id(self):
        if self._explicit_display_file_id is not None:
            return self._explicit_display_file_id
        else:
            return self._exec_file_id

    @property
    def _state(self):
        """Save the player state"""
        return (self._file_ids_stack.copy(), self._lineno, self._old_display_filename,
                self._scroll_index, self._block_id, self._bytecode_pos)

    @_state.setter
    def _state(self, value):
        """Restore the player to previously saved state"""
        # read the block_id and load the block
        self._map_blocks = None
        self._block_id = value[4]
        self._read_block()
        # restore other state attributes
        (self._file_ids_stack, self._lineno, self._old_display_filename,
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

    def _iterate_block_pos_timestamps(self, ts_start, ts_end=None):
        yield (-1, ts_start)
        last_timestamp = ts_start
        for pos in (self._bytecode == OpCodes.TIMESTAMP).nonzero()[0]:
            # decode the timestamp (was encoded in recorder.py)
            ts_offset = 0
            for n in self._bytecode[pos+4:pos:-1]:
                ts_offset <<= 15
                ts_offset += n - 1
            ts = last_timestamp + ts_offset
            yield (pos, ts)
            last_timestamp = ts
        if ts_end is not None:
            yield (MAP_BLOCK_UINT16_SIZE, ts_end)

    def _compute_pos_timestamps(self):
        ts_start, ts_end = self._get_block_ts_boundaries()
        timestamps = self._iterate_block_pos_timestamps(ts_start, ts_end)
        # Each timestamp is assigned to the next lineno instruction of
        # the bytecode. Timestamps of other lineno instructions are
        # linearly interpolated.
        next_ts_pos, next_ts = next(timestamps)
        self._timestamps_per_pos = {}
        for lineno in self._browse_block_line_numbers(preserve_state=True):
            pos = self._bytecode_pos - 1  # self._bytecode_pos is actually the next pos
            if pos > next_ts_pos:
                # 1st lineno after the timestamp, assign
                ts = next_ts
                # prepare linear interpolation for next linenos
                prev_ts = ts
                prev_ts_1st_lineno_pos = pos
                # update info about next timestamp
                while pos > next_ts_pos:
                    next_ts_pos, next_ts = next(timestamps)
            else:
                # linear interpolation
                ts_offset = int(next_ts - prev_ts)
                ts_offset *= (pos - prev_ts_1st_lineno_pos)
                ts_offset /= (next_ts_pos - prev_ts_1st_lineno_pos)
                ts = int(prev_ts + ts_offset)
            # save
            self._timestamps_per_pos[pos] = ts
        # restore modified state
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
                if (self._exec_file_id, self._lineno) in self._breakpoints:
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
                    if (self._exec_file_id, self._lineno) in self._breakpoints:
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
        if self._block_id >= len(self._index_blocks):
            self._block_id = len(self._index_blocks) -1
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
        if self._help_screen:
            return MD_HELP_SCREEN, 0
        breakpoints = tuple(
                str(lineno) for (file_id, lineno) in self._breakpoints
                if file_id == self._display_file_id)
        code_flags = "linenos breakpoints=" + ",".join(breakpoints)
        if self._display_file_id == self._exec_file_id:
            if self._lineno is None:
                self._step_file_and_lineno()
            code_flags += f" highlight-line={self._lineno}"
        source_text = (self._log_sources_path / self._display_filename).read_text()
        md_text = (f"""
```python3 {code_flags}
{source_text}```
""")
        if self._update_scrolling and self._lineno is not None:
            # by default, we compute the index (scrolling position) to have
            # the highlighted line at one 5th of the screen (or upper if
            # targetting one of the first lines of the file).
            # if same file (only the line number changed),
            # check if we should really update this index, or if the old one
            # is still fine.
            scroll_index = max(0, self._lineno - (rows//5))
            if (
                    self._display_filename == self._old_display_filename and
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
            block_ts_end = self._endtime
        else:
            block_ts_end = self._index_blocks[self._block_id+1]['timestamp']
        return block_ts_start, block_ts_end

    def _approximate_timestamp(self):
        return self._timestamps_per_pos[self._bytecode_pos-1]

    def _timestamp_to_datetime(self, ts):
        return datetime.fromtimestamp(float(ts) / SEC_AS_TS)

    def get_header_text(self, cols, **env):
        if self._help_screen:
            return ""  # no header
        location = f"{self._display_filename}:{self._lineno}"
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

    def get_footer_help_keys(self, **env):
        return (
            '"q": quit', '"h": help about all commands'
        )

    def _suffix_matches(self, prefix, fragment):
        for f in self._filenames:
            idx = 0
            while True:
                idx = f.find(fragment, idx)
                if idx == -1:
                    break
                yield prefix + f[idx:]
                idx += 1

    def complete(self, text, state):
        if state == 0:  # on first trigger, build possible matches
            words = text.split()
            if len(words) != 2 or words[0] != "f" or len(words[1]) < 2:
                self._compl_matches = []
            else:
                fragment = words[1]
                prefix = text[:-len(fragment)]
                self._compl_matches = list(set(
                    self._suffix_matches(prefix, fragment)))
        # return match indexed by state
        try:
            return self._compl_matches[state]
        except IndexError:
            return None

    def handle_keypress(self, c, **env):
        # ignored chars
        if c in "~\x1b[":
            return
        # set default values, update below when relevant
        self.error_message = None
        self._update_scrolling = False
        exec_cmds = {
            "n": self._next_file_and_lineno,
            "s": self._step_file_and_lineno,
            "c": self._continue
        }
        # <h>: toggle help screen
        if c == "h":
            self._help_screen = not self._help_screen
            # if leaving the help screen, recompute appropriate
            # scrolling position for displaying the source file
            # (it was set to zero when entering help)
            if not self._help_screen:
                self._update_scrolling = True
            return Pager.UPDATE_MD_CONTENT_NO_RETURN
        elif self._help_screen:
            return  # only <h> allows to quit the help screen
        # <q>: quit
        if c == "q":
            return Pager.QUIT
        # arrow keys, page up / down: scroll
        if c == "A":  # up   (we get '\x1b[A')
            return Pager.SCROLL_UP
        if c == "B":  # down
            return Pager.SCROLL_DOWN
        if c == "5":  # up
            return Pager.SCROLL_PAGE_UP
        if c == "6":  # down
            return Pager.SCROLL_PAGE_DOWN
        if c in exec_cmds:
            # next/step/continue
            state = self._state  # save state
            self._old_display_filename = self._display_filename
            if exec_cmds[c]():
                # next/step/continue worked
                # if a different file was displayed, return
                # to the one related to the executed section.
                self._explicit_display_file_id = None
                # let the pager update the screen
                self._update_scrolling = True
                return Pager.UPDATE_MD_CONTENT_NO_RETURN
            else:  # failed
                self._state = state   # restore previous state
        else:
            # full-line commands
            prefill = None
            if c.isalpha() and c.lower() == c:
                # <b> => prefill "b "; <f> => prefill "f "; etc.
                prefill = c + " "
            cmd = self.prompt_command(prefill_text=prefill,
                                      completer=self).strip()
            if cmd == "":
                return Pager.UPDATE_MD_CONTENT_NO_RETURN
            cmd_args = cmd.split()
            try:
                if cmd_args[0] == "b":
                    # toggle a breakpoint
                    if len(cmd_args) == 1:
                        if self._display_file_id != self._exec_file_id:
                            self.error_message = (
                                "Error: explicit line number needed. "
                                "The current execution line is in another file."
                            )
                            lineno = -1
                        else:
                            lineno = self._lineno
                    else:
                        lineno = int(cmd_args[1])
                    if lineno > 0 and self._toggle_breakpoint(lineno):
                        return Pager.UPDATE_MD_CONTENT_NO_RETURN
                elif cmd_args[0] == "j":
                    # jump in time
                    time_spec = cmd_args[1]
                    curr_ts = self._approximate_timestamp()
                    if time_spec[0] in "+-":
                        # relative jump
                        offset, unit = time_spec[:-1], time_spec[-1]
                        offset = float(offset)
                        offset *= {
                                "s": SEC_AS_TS,
                                "m": MIN_AS_TS,
                                "h": HOUR_AS_TS,
                                "d": DAY_AS_TS,
                        }[unit]
                        ts = curr_ts + offset
                    else:
                        curr_unix_ts = curr_ts / SEC_AS_TS
                        if ':' in time_spec:
                            # set time
                            h, m, s = time_spec.split(':')
                            h, m, s = int(h), int(m), float(s)
                            curr_date = date.fromtimestamp(curr_unix_ts)
                            dt = datetime.combine(curr_date, midnight())
                            dt += timedelta(hours=h, minutes=m, seconds=s)
                        else:
                            # set date
                            y, m, d = time_spec.split('-')
                            y, m, d = int(y), int(m), int(d)
                            curr_time = datetime.fromtimestamp(curr_unix_ts).time()
                            selected_date = date(year=y, month=m, day=d)
                            dt = datetime.combine(selected_date, curr_time)
                        ts = int(dt.timestamp() * SEC_AS_TS)
                    self._jump(ts)
                    # if a different file was displayed, ignore and display
                    # the one related to the point in time we jumped to.
                    self._explicit_display_file_id = None
                    self._update_scrolling = True
                    return Pager.UPDATE_MD_CONTENT_NO_RETURN
                elif cmd_args[0] == "f":
                    file_suffix = cmd_args[1]
                    matching_file_ids = [
                        i for i, f in enumerate(self._filenames)
                        if f.endswith(file_suffix)
                    ]
                    num_matches = len(matching_file_ids)
                    if num_matches > 1:
                        self.error_message = (
                            f"Error: {num_matches} different file paths could match.")
                    elif num_matches == 0:
                        self.error_message = (
                            f"Error: could not find a matching file path "
                            "in the exec trace.")
                    else:
                        # ok
                        self._explicit_display_file_id = matching_file_ids[0]
                        self._scroll_index = 0
                        return Pager.UPDATE_MD_CONTENT_NO_RETURN
            except Exception:
                pass    # invalid, the default
            if self.error_message is None:
                self.error_message = (
                    f"Invalid command: {repr(cmd)} -- press <h> for help")
        # if we get here, something went wrong
        assert self.error_message is not None
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
