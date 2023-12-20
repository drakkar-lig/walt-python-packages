BLOCK_UINT16_SIZE = 4096
BLOCK_SIZE = BLOCK_UINT16_SIZE * 2


class OpCodes:
    CALL = 65535
    RETURN = 65534
    END = 0  # end of block
    # note: other values are used for line numbers.
