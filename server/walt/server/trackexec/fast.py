from numba import njit, i2, u2, u8
from numba.types import Array
import numpy as np

from walt.server.trackexec.const import MAP_BLOCK_UINT16_SIZE


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


@njit((u8,u8,u8[:],u2,u2), cache=True)
def _fast_apply_linear_timestamps(last_ts, new_ts,
        locations_timestamps, locations_ts_start, locations_ts_end):
    n_steps = locations_ts_end - locations_ts_start +1
    linear_ts_range = np.linspace(last_ts, new_ts, n_steps)[:-1].astype(np.uint64)
    locations_timestamps[locations_ts_start:locations_ts_end] = linear_ts_range


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
    locations_pos = u2(0)
    locations_ts_start = i2(-1)
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
            new_ts = _fast_decode_timestamp(last_ts, bytecode, u2(bytecode_pos))
            if locations_ts_start != -1:
                _fast_apply_linear_timestamps(last_ts, new_ts,
                    locations_timestamps, locations_ts_start, locations_pos)
                locations_ts_start = -1
            last_ts = new_ts
            bytecode_pos += 4
        else:  # opcode is a line number
            file_id = file_ids_stack[file_ids_stack_pos-1]
            locations_lineno[locations_pos] = opcode
            locations_file_id[locations_pos] = file_id
            locations_stack_depths[locations_pos] = file_ids_stack_pos
            if locations_ts_start == -1:
                # first lineno after a timestamp
                locations_ts_start = locations_pos
            locations_pos += 1
    if block_ts_end == 0:
        block_ts_end = last_ts
    if locations_ts_start != -1:
        _fast_apply_linear_timestamps(last_ts, block_ts_end,
                locations_timestamps, locations_ts_start, locations_pos)
    return (locations_file_id[:locations_pos],
            locations_lineno[:locations_pos],
            locations_stack_depths[:locations_pos],
            locations_timestamps[:locations_pos])


# compute duration of each instruction, from the time it started
# to the next instruction with a lower or equal stack depth, or to
# the end of the block.
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
    return durations
