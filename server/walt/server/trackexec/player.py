import numpy as np
import sys

from collections import defaultdict
from datetime import datetime, timedelta, date, time as midnight
from pathlib import Path
from plumbum import cli
from walt.doc.pager import Pager, SCROLL_HELP
from walt.server.trackexec.const import (
        SEC_AS_TS, MIN_AS_TS, HOUR_AS_TS, DAY_AS_TS
)
from walt.server.trackexec.reader import LogsReader


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


class TrackExecPlayer(Pager):

    def __init__(self, dir_path):
        Pager.__init__(self)
        self._reader = LogsReader(dir_path)
        self._old_display_filename = None
        self._src_index = None
        self._breakpoints = set()
        self._num_breakpoints_per_block_id = defaultdict(int)
        self._block_source_data_idx = 0
        self._update_scrolling = True
        self._help_screen = False
        self._explicit_display_file_id = None

    def load(self):
        self._reader.seek(0)
        # force reader to compute source index now
        self._src_index = self._reader.src_index
        self._reader.seek(0)

    @property
    def _block_source_data(self):
        return self._reader.block_source_data

    @property
    def _exec_point(self):
        return self._block_source_data[self._block_source_data_idx]

    def _toggle_breakpoint(self, lineno):
        bp = (self._display_file_id, lineno)
        if bp in self._breakpoints:
            # remove bp
            self._breakpoints.discard(bp)
            for block_id in self._src_index[bp][0]:
                self._num_breakpoints_per_block_id[block_id] -= 1
        else:
            # add bp
            valid_line = False
            for block_id in self._src_index[bp][0]:
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
        return self._reader.filenames[self._display_file_id]

    @property
    def _exec_file_id(self):
        return self._exec_point.file_id

    @property
    def _display_file_id(self):
        if self._explicit_display_file_id is not None:
            return self._explicit_display_file_id
        else:
            return self._exec_file_id

    @property
    def _state(self):
        """Save the player state"""
        return (self._reader.current_block_id,
                self._block_source_data_idx,
                self._old_display_filename,
                self._scroll_index)

    @_state.setter
    def _state(self, value):
        """Restore the player to previously saved state"""
        # restore state values and reload the block
        (block_id,
         self._block_source_data_idx,
         self._old_display_filename,
         self._scroll_index) = value
        self._reader.seek(block_id)

    def _is_end_of_block(self):
        return self._block_source_data_idx == len(self._block_source_data) -1

    def _is_start_of_trace(self):
        if self._reader.current_block_id > 0:
            return False
        if self._block_source_data_idx > 0:
            return False
        return True

    def _is_end_of_trace(self):
        if not self._reader.at_last_block():
            return False
        return self._is_end_of_block()

    def _block_has_breakpoints(self):
        return self._num_breakpoints_per_block_id[self._reader.current_block_id] > 0

    def _jump_to_next_block(self):
        self._reader.next()
        self._block_source_data_idx = 0

    def _step_no_message(self):
        if self._is_end_of_trace():
            return False
        else:
            if self._is_end_of_block():
                self._jump_to_next_block()
            else:
                self._block_source_data_idx += 1
            return True

    def _step(self, err_msg='"step" failed: reached the end of exec trace'):
        res = self._step_no_message()
        if not res:
            self.error_message = err_msg
        return res

    def _next(self):
        init_stack_depth = self._exec_point.stack_depth
        err_msg='"next" failed: reached the end of exec trace'
        # single-step at least once
        if not self._step(err_msg):
            return False
        # loop until we have a breakpoint, the end of trace,
        # or the stack depth back to its original level
        while True:
            # check if we should further analyse the block
            if (self._reader.current_block_min_stack_size > init_stack_depth
                    and not self._block_has_breakpoints()
               ):
                # we know we will not stop in this block
                if self._reader.at_last_block():
                    self.error_message = err_msg  # end of trace, "next" failed
                    return False
                else:
                    self._jump_to_next_block()  # try next block
                    continue
            # process the block
            while True:
                # test if "next" operation terminates here
                if self._exec_point.stack_depth <= init_stack_depth:
                    return True
                # test if we should stop because of a breakpoint
                if (self._exec_file_id, self._exec_point.lineno) in self._breakpoints:
                    return True
                # single step
                if not self._step(err_msg):
                    return False  # end of trace, "next" failed
                if self._block_source_data_idx == 0:
                    # start of a new block, return to top-level loop
                    break

    def _continue(self):
        # note: unless called already at the end of the trace, reaching the end
        # of the trace is not an error with "continue".
        if not self._step('"continue" failed: already at the end of exec trace'):
            return False
        # loop until we have a breakpoint or the end of trace
        while True:
            # check if we should further analyse the block
            if not self._block_has_breakpoints():
                # we know we will not stop in this block
                if self._reader.at_last_block():
                    # jump to the end of the block (= end of the trace)
                    self._block_source_data_idx = len(self._block_source_data) -1
                    return True
                else:
                    self._jump_to_next_block()  # try next block
                    continue
            # process the block
            while True:
                # test if we should stop because of a breakpoint
                if (self._exec_file_id, self._exec_point.lineno) in self._breakpoints:
                    return True
                # single step
                if not self._step_no_message():
                    return True  # end of trace
                if self._block_source_data_idx == 0:
                    # start of a new block, return to top-level loop
                    break

    def _jump(self, target_ts):
        self._reader.seek_by_timestamp(target_ts)
        # Sometimes we want to jump at a time previously reported by the viewer
        # using a "HH:MM:SS.ssssss" format.
        # Because of the floating point format precision, the timestamps in the
        # log trace may be slightly different. The following process manipulates
        # those values to make them look as if they were all entered with this
        # "HH:MM:SS.ssssss" format.
        ts = self._block_source_data.timestamp / SEC_AS_TS
        decimals, integrals = np.modf(ts)
        ts = np.add(integrals, np.rint(decimals*1000000) / 1000000) * SEC_AS_TS
        ts = ts.astype(np.uint64)
        # find the line opcode just before the target timestamp:
        # ts(data_idx) <= target_ts < ts(data_idx+1)
        # => np.searchsorted() will return data_idx+1 (insert position maintaining
        #    the order)
        # => we want to point the viewer at data_idx instead, the last instruction
        #    before target_ts. This rule increases the chances to display
        #    long-running instructions, i.e., those instructions where
        #    the delay (ts(data_idx+1)-ts(data_idx)) is long.
        self._block_source_data_idx = np.searchsorted(ts, target_ts, side="right") -1
        if self._block_source_data_idx < 0:
            self._block_source_data_idx = 0
        return True

    def get_md_content(self, rows, **env):
        if self._help_screen:
            return MD_HELP_SCREEN, 0
        breakpoints = tuple(
                str(lineno) for (file_id, lineno) in self._breakpoints
                if file_id == self._display_file_id)
        code_flags = "linenos breakpoints=" + ",".join(breakpoints)
        scroll_index = self._scroll_index   # by default, keep scrolling position
        if self._display_file_id == self._exec_file_id:
            lineno = self._exec_point.lineno
            code_flags += f" highlight-line={lineno}"
            if self._update_scrolling:
                # by default, we compute the index (scrolling position) to have
                # the highlighted line at one 5th of the screen (or upper if
                # targetting one of the first lines of the file).
                # if same file (only the line number changed),
                # check if we should really update this index, or if the old one
                # is still fine.
                if not (
                        self._display_filename == self._old_display_filename and
                        lineno - self._scroll_index > 5 and
                        self._scroll_index + rows - lineno > 5
                   ):
                    # the old scrolling position is no longer appropriate, update it
                    scroll_index = max(0, lineno - (rows//5))
        source_text = self._reader.read_source_file(self._display_file_id)
        md_text = (f"""
```python3 {code_flags}
{source_text}```
""")
        return md_text, scroll_index

    def _approximate_timestamp(self):
        return self._block_source_data.timestamp[self._block_source_data_idx]

    def _timestamp_to_datetime(self, ts):
        return datetime.fromtimestamp(float(ts) / SEC_AS_TS)

    def get_header_text(self, cols, **env):
        if self._help_screen:
            return ""  # no header
        if self._display_file_id == self._exec_file_id:
            lineno = self._exec_point.lineno
        else:
            lineno = None
        location_maxlen = cols - len("location: ")
        location = self._reader.short_file_location(
                self._display_file_id, lineno, location_maxlen)
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
        for f in self._reader.filenames:
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
            "n": self._next,
            "s": self._step,
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
                            lineno = self._exec_point.lineno
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
                        i for i, f in enumerate(self._reader.filenames)
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
                        self.set_scroll_index(0)
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
        player.load()
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
