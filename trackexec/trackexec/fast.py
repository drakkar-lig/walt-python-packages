from numba import njit, i2, u2, u8, b1
from numba.types import Array
import numpy as np

from trackexec.const import MAP_BLOCK_UINT16_SIZE


# Some function args such as "startup_stack" and "bytecode" of
# fast_analyse_block() come from subitems of a structured array,
# so they are read-only.
def ro(t):
    return Array(t.dtype, t.ndim, 'A', readonly=True)


# decode the timestamp (was encoded in recorder.py)
TS_LEFT_SHIFTS = np.array([0, 15, 30, 45], dtype=np.uint64)
@njit((u8,ro(u2[:]),u2), cache=True)
def _fast_decode_timestamp(last_timestamp, bytecode, pos):
    offset = np.left_shift(
            (bytecode[pos:pos+4]-1).astype(np.uint64),
            TS_LEFT_SHIFTS).sum()
    return offset + last_timestamp


# Assign timestamps to the locations recorded between two timestamps,
# by linear interpolation.
# Return markers (locations with lineno 0, see fast_analyse_block())
# are not considered in this interpolation: a return marker directly
# following a TIMESTAMP opcode gets this timestamp, others get the
# timestamp of the next location (or new_ts).
@njit((u8,u8,u8[:],u2[:],b1[:],u2,u2), cache=True)
def _fast_apply_linear_timestamps(last_ts, new_ts,
        locations_timestamps, locations_lineno, locations_after_ts,
        locations_ts_start, locations_ts_end):
    n = 0
    for i in range(locations_ts_start, locations_ts_end):
        if locations_lineno[i] != 0:
            n += 1
    if n > 0:
        linear_ts_range = np.linspace(last_ts, new_ts, n + 1)[:-1].astype(np.uint64)
        j = 0
        for i in range(locations_ts_start, locations_ts_end):
            if locations_lineno[i] != 0:
                locations_timestamps[i] = linear_ts_range[j]
                j += 1
    if n < locations_ts_end - locations_ts_start:
        # there are return markers
        next_ts = new_ts
        for i in range(locations_ts_end - 1, locations_ts_start - 1, -1):
            if locations_lineno[i] != 0:
                next_ts = locations_timestamps[i]
            elif locations_after_ts[i]:
                locations_timestamps[i] = last_ts
            else:
                locations_timestamps[i] = next_ts


# This function decodes a block: it returns the locations (file id, line
# number, stack depth and timestamp) found in the block, in order.
# RETURN opcodes are also returned as locations with lineno 0
# ("return markers"), at the stack depth of the frame which returns;
# they allow to end the duration of the last instruction of this frame
# when it returns.
# It also returns the last timestamp found in the block, and whether the
# block ends with a timestamp (the recorder ends blocks with a timestamp
# taken before writing the block, for excluding this write from durations).
# This function is called for each block when building the source
# index or computing hot points stats. There may be many blocks to
# read, depending on how long the process execution has been. For
# this reason, we use numba to accelerate this processing by several
# orders of magnitude.
@njit((ro(u2[:]),ro(u2[:]),u2,u2,u2,u2,u8,u8), cache=True)
def fast_analyse_block(startup_stack, bytecode,
        op_call, op_return, op_end, op_timestamp,
        block_ts_start, block_ts_end):
    last_ts = block_ts_start
    bytecode_pos = u2(0)
    file_ids_stack = np.empty(MAP_BLOCK_UINT16_SIZE, np.uint16)
    file_ids_stack_pos = len(startup_stack)
    file_ids_stack[0:file_ids_stack_pos] = startup_stack
    locations_lineno = np.empty(MAP_BLOCK_UINT16_SIZE, np.uint16)
    locations_file_id = np.empty(MAP_BLOCK_UINT16_SIZE, np.uint16)
    locations_stack_depths = np.empty(MAP_BLOCK_UINT16_SIZE, np.uint16)
    locations_timestamps = np.empty(MAP_BLOCK_UINT16_SIZE, np.uint64)
    locations_after_ts = np.zeros(MAP_BLOCK_UINT16_SIZE, np.bool_)
    locations_pos = u2(0)
    locations_ts_start = i2(-1)
    prev_is_ts = False
    while True:
        opcode = bytecode[bytecode_pos]
        bytecode_pos += 1
        if opcode == op_call:
            file_id = bytecode[bytecode_pos]
            bytecode_pos += 1
            file_ids_stack[file_ids_stack_pos] = file_id
            file_ids_stack_pos += 1
        elif opcode == op_return:
            if file_ids_stack_pos > 0:
                # add a return marker
                locations_lineno[locations_pos] = 0
                locations_file_id[locations_pos] = file_ids_stack[file_ids_stack_pos-1]
                locations_stack_depths[locations_pos] = file_ids_stack_pos
                locations_after_ts[locations_pos] = prev_is_ts
                if locations_ts_start == -1:
                    locations_ts_start = locations_pos
                locations_pos += 1
                file_ids_stack_pos -= 1
        elif opcode == op_end:
            break
        elif opcode == op_timestamp:
            new_ts = _fast_decode_timestamp(last_ts, bytecode, u2(bytecode_pos))
            if locations_ts_start != -1:
                _fast_apply_linear_timestamps(last_ts, new_ts,
                    locations_timestamps, locations_lineno, locations_after_ts,
                    locations_ts_start, locations_pos)
                locations_ts_start = -1
            last_ts = new_ts
            bytecode_pos += 4
            prev_is_ts = True
            continue
        else:  # opcode is a line number
            file_id = file_ids_stack[file_ids_stack_pos-1]
            locations_lineno[locations_pos] = opcode
            locations_file_id[locations_pos] = file_id
            locations_stack_depths[locations_pos] = file_ids_stack_pos
            if locations_ts_start == -1:
                # first lineno after a timestamp
                locations_ts_start = locations_pos
            locations_pos += 1
        prev_is_ts = False
    if block_ts_end == 0:
        block_ts_end = last_ts
    if locations_ts_start != -1:
        _fast_apply_linear_timestamps(last_ts, block_ts_end,
                locations_timestamps, locations_lineno, locations_after_ts,
                locations_ts_start, locations_pos)
    return (locations_file_id[:locations_pos],
            locations_lineno[:locations_pos],
            locations_stack_depths[:locations_pos],
            locations_timestamps[:locations_pos],
            last_ts, prev_is_ts)


# compute duration of each instruction, from the time it started
# to the next instruction with a lower or equal stack depth, or to
# the end of the block.
# also return the indices of the instructions which were still running
# at the end of the block (by increasing stack depth).
@njit((u2[:],u8[:],u8), cache=True)
def fast_compute_durations(locations_stack_depths, locations_timestamps,
                           block_ts_end):
    durations = np.empty(len(locations_stack_depths), np.uint64)
    pending_indices = np.empty(len(locations_stack_depths), np.uint16)
    num_pending_indices = 0
    for location_pos in np.arange(len(locations_stack_depths)):
        while num_pending_indices > 0:
            idx = pending_indices[num_pending_indices-1]
            if locations_stack_depths[location_pos] <= locations_stack_depths[idx]:
                # instruction at index idx just returned
                durations[idx] = (
                        locations_timestamps[location_pos] -
                        locations_timestamps[idx]
                )
                num_pending_indices -= 1
            else:
                break
        pending_indices[num_pending_indices] = location_pos
        num_pending_indices += 1
    # remaining pending instructions continue up to the end of the block
    for idx in pending_indices[:num_pending_indices]:
        durations[idx] = (
                block_ts_end - locations_timestamps[idx]
        )
    return durations, pending_indices[:num_pending_indices]
