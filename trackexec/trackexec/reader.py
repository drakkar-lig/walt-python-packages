import gzip
import numpy as np
import pickle
import tarfile

from collections import defaultdict
from functools import cache

from trackexec.const import (
        MAP_BLOCK_ID_MASK, MAP_BLOCK_ID_SHIFT, OpCodes,
        SOURCES_INDEX_VERSION, LINENO_UNDEFINED
)
from trackexec.fast import fast_analyse_block
from trackexec.fast import fast_compute_durations
from trackexec.tools import (
        map_block_dt, index_block_dt, LogAbstractManagement
)


class _SourcesIndexUnpickler(pickle.Unpickler):
    # Before trackexec became a standalone package, its code was at
    # walt.server.trackexec, and this module path was saved in the
    # sources index file of existing traces.
    def find_class(self, module, name):
        if module.startswith("walt.server.trackexec."):
            module = "trackexec." + module[len("walt.server.trackexec."):]
        return super().find_class(module, name)


class LogsReader(LogAbstractManagement):

    def __init__(self, dir_path):
        LogAbstractManagement.__init__(self, dir_path)
        self._check_format_version()
        self._block_id = 0
        self._index_blocks = np.memmap(self._log_index_path,
                                       dtype=index_block_dt(),
                                       mode='r')
        self._block_source_data = None
        self._map_blocks = None
        self._filenames = None
        self._src_index = None
        self._src_running = None

    @staticmethod
    def _src_index_value_init():
        return [set(), 0, 0, 0]

    def _read_sources_index(self):
        src_index = defaultdict(LogsReader._src_index_value_init)
        if self._log_sources_index_gz_path.exists():
            try:
                with gzip.open(str(self._log_sources_index_gz_path), 'rb') as f_r:
                    version, next_block_id, saved_index, running = (
                            _SourcesIndexUnpickler(f_r).load())
                if version == SOURCES_INDEX_VERSION:
                    src_index.update(saved_index)
                    return next_block_id, src_index, running
            except Exception:
                pass  # this is just a cache: rebuild it from the trace below
        return 0, src_index, {}

    def _write_sources_index(self):
        # note: save a plain dict, not the defaultdict, because pickle
        # would save a reference to its factory function (with its module
        # path), making the file harder to read with other code versions.
        cache_content = pickle.dumps((SOURCES_INDEX_VERSION,
                                      self.max_block_id+1,
                                      dict(self._src_index),
                                      self._src_running))
        with gzip.open(str(self._log_sources_index_gz_path), 'wb') as f_w:
            f_w.write(cache_content)

    @property
    def src_index(self):
        # Even if the src index file exists, the trace may be longer now.
        # Let's point self._block_id to the first block not yet indexed.
        # Note: the src index file encodes a tuple of 4 values:
        # 1. SOURCES_INDEX_VERSION
        # 2. the number of blocks encoded (= the next block_id to encode)
        # 3. a dictionary {(<fild_id>,<lineno>) -> [
        #                                set(<block_ids>),
        #                                <num-occurences>,
        #                                <cum-duration>,
        #                                <max-duration>
        # ]}
        # 4. the instructions still running at the end of the last block
        #    encoded (see self.src_running).
        if self._src_index is None:
            saved_block_id = self._block_id
            next_block_id, self._src_index, self._src_running = (
                    self._read_sources_index())
            num_added_blocks = self.max_block_id +1 - next_block_id
            if num_added_blocks > 0:
                # Analyse blocks which were added to the trace.
                self.seek(next_block_id)
                while True:
                    block_id = self._block_id
                    op_num = block_id + num_added_blocks - self.max_block_id
                    print(f"Updating source index... {op_num}/{num_added_blocks}\r",
                          end="")
                    bdata = self.block_source_data
                    # count number of each distinct <file-id>:<lineno> in the block
                    block_source_f_l = bdata[["file_id", "lineno"]]
                    arr_unq, arr_cnt = np.unique(block_source_f_l, return_counts=True)
                    # save in the src index:
                    # * the fact each <file-id>:<lineno> was found at least once
                    #   in the block
                    # * add to the total number of occurences of each <file-id>:<lineno>
                    for location, cnt in zip(arr_unq, arr_cnt):
                        file_id, lineno = location
                        src_index_item = self._src_index[(file_id, lineno)]
                        src_index_item[0].add(block_id)
                        src_index_item[1] += cnt
                    # compute duration of each <file-id>:<lineno> instruction
                    # found in the block or not consumed from the startup stack
                    durations, pending = self._compute_durations()
                    self._update_max_durations(durations, pending)
                    durations_f_l = durations[["file_id", "lineno"]]
                    # for each distinct <file-id>:<lineno>, sum these durations
                    arr_unq, arr_inv = np.unique(durations_f_l, return_inverse=True)
                    cum_duration = np.zeros(len(arr_unq), dtype=np.uint64)
                    np.add.at(cum_duration, arr_inv, durations.duration)
                    # update the src index:
                    # * add to the cumulated duration of each <file-id>:<lineno>
                    for location, duration in zip(arr_unq, cum_duration):
                        if duration > 0 and location[1] != LINENO_UNDEFINED:
                            file_id, lineno = location
                            src_index_item = self._src_index[(file_id, lineno)]
                            src_index_item[2] += duration
                    # continue with next block if any
                    if self.at_last_block():
                        break
                    else:
                        self.next()
                print()
                # Update the analysis file
                self._write_sources_index()
                # restore context
                self.seek(saved_block_id)
        return self._src_index

    @property
    def filenames(self):
        if self._filenames is None:
            with tarfile.open(self._log_sources_archive_path, "r") as t_r:
                self._filenames = list(
                        ("/" + tar_member.name)
                        for tar_member in t_r.getmembers())
        return self._filenames

    def _short_file_location(self, path_items, lineno, maxlen,
                             allow_double_star=True):
        location = "/".join(path_items) + f":{lineno}"
        if len(location) > maxlen:
            if allow_double_star:
                return "**/" + self._short_file_location(
                        path_items[1:], lineno, maxlen-3, False)
            else:
                return self._short_file_location(
                        path_items[1:], lineno, maxlen, False)
        else:
            return location

    def short_file_location(self, file_id, lineno, maxlen):
        path_items = tuple(self.filenames[file_id].split("/"))
        return self._short_file_location(path_items, lineno, maxlen)

    def seek(self, block_id):
        if self._block_id == block_id:
            return  # nothing to do
        # check if the log map is a different file
        if (self._block_id >> MAP_BLOCK_ID_SHIFT !=
                  block_id >> MAP_BLOCK_ID_SHIFT):
            self._map_blocks = None  # will need to reload the map file
        self._block_id = block_id
        self._block_source_data = None

    def seek_by_timestamp(self, target_ts):
        # ts(blockN) < target_ts < ts(blockN+1) => use blockN
        block_id = np.searchsorted(self._index_blocks['timestamp'], target_ts) - 1
        if block_id < 0:
            block_id = 0
        if block_id >= len(self._index_blocks):
            block_id = len(self._index_blocks) -1
        self.seek(block_id)

    @property
    def max_block_id(self):
        return len(self._index_blocks) - 1

    @property
    def current_block_id(self):
        return self._block_id

    @property
    def current_block_min_stack_size(self):
        return self._index_blocks[self._block_id]['min_stack_size']

    @property
    def block_source_data(self):
        if self._block_source_data is None:
            self._block_source_data = self._read_block()
        return self._block_source_data

    def at_last_block(self):
        return self._block_id == len(self._index_blocks) - 1

    @property
    def _block(self):
        map_block_id = self._block_id & MAP_BLOCK_ID_MASK
        block = self._map_blocks[map_block_id]
        stack_size = block['stack_size']
        return self._map_blocks[map_block_id:map_block_id+1].view(
                        dtype=map_block_dt(stack_size))[0]

    def _read_block(self):
        if self._map_blocks is None:
            self._log_map_num = self._block_id >> MAP_BLOCK_ID_SHIFT
            if self._log_map_path.exists():
                map_bytes = self._log_map_path.read_bytes()
            elif self._log_map_gz_path.exists():
                with gzip.open(str(self._log_map_gz_path), 'rb') as f_r:
                    map_bytes = f_r.read()
            self._map_blocks = np.frombuffer(map_bytes, dtype=map_block_dt(1))
        block_ts_start = self._index_blocks[self._block_id]['timestamp']
        if self.at_last_block():
            block_ts_end = 0  # end timestamp of last block unknown for now
        else:
            block_ts_end = self._index_blocks[self._block_id+1]['timestamp']
        block = self._block
        (source_file_ids, source_linenos, source_stack_depths,
         source_ts) = fast_analyse_block(
                block["stack"]["file_id"], block["bytecode"],
                OpCodes.CALL, OpCodes.RETURN, OpCodes.END, OpCodes.TIMESTAMP,
                block_ts_start, block_ts_end)
        block_source_data = np.recarray(len(source_linenos), np.dtype([
                ("file_id", np.uint16),
                ("lineno", np.uint16),
                ("stack_depth", np.uint16),
                ("timestamp", np.uint64)
        ]))
        block_source_data.file_id = source_file_ids
        block_source_data.lineno = source_linenos
        block_source_data.stack_depth = source_stack_depths
        block_source_data.timestamp = source_ts
        return block_source_data

    def _update_max_durations(self, durations, pending):
        # The first rows of durations are the instructions of the startup
        # stack of the block (row i has stack depth i+1); they may be the
        # continuation of instructions still running at the end of the
        # previous block (self._src_running). Add these durations, for
        # computing the full duration of each instruction execution.
        stack_size = len(self._block["stack"])
        totals = durations.duration.copy()
        for depth, (file_id, lineno, partial) in self._src_running.items():
            if depth <= stack_size:
                row = durations[depth-1]
                if (row.file_id, row.lineno) == (file_id, lineno):
                    totals[depth-1] += partial
        # instructions still running at the end of this block will
        # continue in the next block
        running = {}
        is_pending = np.zeros(len(durations), dtype=bool)
        is_pending[pending] = True
        for depth, idx in enumerate(pending, start=1):
            row = durations[idx]
            running[depth] = (int(row.file_id), int(row.lineno),
                              int(totals[idx]))
        self._src_running = running
        # update the max duration of completed instructions
        # (as for the cumulated duration, ignore zero durations, to avoid
        # creating index entries for instructions of the startup stack
        # which are not actually executed in the trace)
        done = ~is_pending & (durations.lineno != LINENO_UNDEFINED) & (totals > 0)
        if not done.any():
            return
        locations = durations[["file_id", "lineno"]][done]
        arr_unq, arr_inv = np.unique(locations, return_inverse=True)
        max_duration = np.zeros(len(arr_unq), dtype=np.uint64)
        np.maximum.at(max_duration, arr_inv, totals[done])
        for location, duration in zip(arr_unq, max_duration):
            file_id, lineno = location
            src_index_item = self._src_index[(file_id, lineno)]
            if duration > src_index_item[3]:
                src_index_item[3] = int(duration)

    @property
    def src_running(self):
        """Instructions still running at the end of the trace, as a dict
        {<stack-depth>: (<file-id>, <lineno>, <duration-so-far>)}"""
        self.src_index  # ensure it is up to date
        return self._src_running

    def _compute_durations(self):
        bdata = self.block_source_data
        block_ts_start = self._index_blocks[self._block_id]['timestamp']
        if self.at_last_block():
            block_ts_end = bdata["timestamp"][-1]
        else:
            block_ts_end = self._index_blocks[self._block_id+1]['timestamp']
        # we must also compute duration of the instructions of the stack,
        # even if they are not referenced in the block.
        # for this, we prepend these instructions to bdata, considering
        # they started at block_ts_start, since we only want to compute
        # the duration of instructions within the boundaries of the block.
        stack = self._block["stack"]
        durations_data_len = len(stack) + len(bdata)
        durations_data = np.recarray(durations_data_len, np.dtype([
                ("file_id", np.uint16),
                ("lineno", np.uint16),
                ("stack_depth", np.uint16),
                ("timestamp", np.uint64),
                ("duration", np.uint64)
        ]))
        # fill values of these prepended rows
        prepended = durations_data[:len(stack)]
        prepended.file_id = stack["file_id"]
        prepended.lineno = stack["lineno"]
        prepended.stack_depth = np.arange(1, len(stack)+1)
        prepended.timestamp = block_ts_start
        # copy bdata to the following rows
        bdata_fields = ["file_id", "lineno", "stack_depth", "timestamp"]
        durations_data[len(stack):][bdata_fields] = bdata
        # compute "duration" column
        durations, pending = fast_compute_durations(
            durations_data.stack_depth, durations_data.timestamp,
            block_ts_end)
        durations_data.duration = durations
        # return selected columns, and the indices of the instructions
        # still running at the end of the block
        return durations_data[["file_id", "lineno", "duration"]], pending

    def next(self):
        self.seek(self._block_id + 1)

    @cache
    def read_source_file(self, file_id):
        with tarfile.open(self._log_sources_archive_path, "r") as t_r:
            tar_member = t_r.getmembers()[file_id]
            return t_r.extractfile(tar_member).read().decode("UTF-8")
