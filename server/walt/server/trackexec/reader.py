import gzip
import numpy as np
import pickle
import tarfile

from collections import defaultdict
from functools import cache

from walt.server.trackexec.const import (
        MAP_BLOCK_ID_MASK, MAP_BLOCK_ID_SHIFT, OpCodes
)
from walt.server.trackexec.fast import fast_analyse_block
from walt.server.trackexec.fast import fast_compute_durations
from walt.server.trackexec.tools import (
        map_block_dt, index_block_dt, LogAbstractManagement
)


class LogsReader(LogAbstractManagement):

    def __init__(self, dir_path):
        LogAbstractManagement.__init__(self, dir_path)
        self._block_id = 0
        self._index_blocks = np.memmap(self._log_index_path,
                                       dtype=index_block_dt(),
                                       mode='r')
        self._block_source_data = None
        self._map_blocks = None
        self._filenames = None
        self._src_index = None

    @staticmethod
    def _src_index_value_init():
        return [set(), 0, 0]

    def _read_sources_index(self):
        if self._log_sources_index_gz_path.exists():
            with gzip.open(str(self._log_sources_index_gz_path), 'rb') as f_r:
                cache_content = f_r.read()
            return pickle.loads(cache_content)
        else:
            return (0, defaultdict(LogsReader._src_index_value_init))

    def _write_sources_index(self):
        cache_content = pickle.dumps((self.max_block_id+1, self._src_index))
        with gzip.open(str(self._log_sources_index_gz_path), 'wb') as f_w:
            f_w.write(cache_content)

    @property
    def src_index(self):
        # Even if the src index file exists, the trace may be longer now.
        # Let's point self._block_id to the first block not yet indexed.
        # Note: the src index file encodes a tuple of 2 values:
        # 1. the number of blocks encoded (= the next block_id to encode)
        # 2. a dictionary {(<fild_id>,<lineno>) -> [
        #                                set(<block_ids>),
        #                                <num-occurences>,
        #                                <cum-duration>
        # ]}
        if self._src_index is None:
            saved_block_id = self._block_id
            next_block_id, self._src_index = self._read_sources_index()
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
                    durations = self._compute_durations()
                    durations_f_l = durations[["file_id", "lineno"]]
                    # for each distinct <file-id>:<lineno>, sum these durations
                    arr_unq, arr_inv = np.unique(durations_f_l, return_inverse=True)
                    cum_duration = np.zeros(len(arr_unq), dtype=np.uint64)
                    np.add.at(cum_duration, arr_inv, durations.duration)
                    # update the src index:
                    # * add to the cumulated duration of each <file-id>:<lineno>
                    for location, duration in zip(arr_unq, cum_duration):
                        if duration > 0:
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
        durations_data.duration = fast_compute_durations(
            durations_data.stack_depth, durations_data.timestamp,
            block_ts_end)
        # return selected columns
        return durations_data[["file_id", "lineno", "duration"]]

    def next(self):
        self.seek(self._block_id + 1)

    @cache
    def read_source_file(self, file_id):
        with tarfile.open(self._log_sources_archive_path, "r") as t_r:
            tar_member = t_r.getmembers()[file_id]
            return t_r.extractfile(tar_member).read().decode("UTF-8")
