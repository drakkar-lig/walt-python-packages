# MAP_BLOCK_UINT16_SIZE and MAP_BLOCK_ID_SHIFT were selected
# according to tests giving high compressability of the resulting
# MAP_FILE_SIZE chunks.
MAP_BLOCK_UINT16_SIZE = 4096
MAP_BLOCK_SIZE = MAP_BLOCK_UINT16_SIZE << 1
MAP_BLOCK_ID_SHIFT = 5
MAP_FILE_SIZE = MAP_BLOCK_SIZE << MAP_BLOCK_ID_SHIFT
NUM_BLOCKS_PER_MAP_FILE = (1 << MAP_BLOCK_ID_SHIFT)
MAP_BLOCK_ID_MASK = (NUM_BLOCKS_PER_MAP_FILE - 1)

# Durations as timestamp (1>>20 second granularity)
SEC_AS_TS = 1048576
MIN_AS_TS = 60 * SEC_AS_TS
HOUR_AS_TS = 60 * MIN_AS_TS
DAY_AS_TS = 24 * HOUR_AS_TS


class OpCodes:
    CALL = 65535
    RETURN = 65534
    TIMESTAMP = 65533
    END = 0  # end of block
    # other opcodes are line numbers
