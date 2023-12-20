import numpy as np

from walt.server.trackexec.const import BLOCK_UINT16_SIZE


def block_max_bytecode_size(stack_size):
    # timestamp 64 bits  -- 4 uint16 large
    # stack_size         -- 1 uint16 large
    # stack              -- <stack_size> uint16 large
    # bytecode           -- up to the BLOCK_UINT16_SIZE limit
    return BLOCK_UINT16_SIZE - (stack_size + 5)


def block_dt(stack_size):
    return np.dtype([('timestamp', np.uint64),
                     ('stack_size', np.uint16),
                     ('stack', np.uint16, (stack_size,)),
                     ('bytecode', np.uint16, (block_max_bytecode_size(stack_size),))])


class Uint16Stack:
    def __init__(self):
        self.array = np.empty(BLOCK_UINT16_SIZE, np.uint16)
        self.level = 0

    def add(self, v):
        self.array[self.level] = v
        self.level += 1

    def pop(self):
        self.level -= 1
        return self.array[self.level]

    def top(self):
        return self.array[self.level-1]

    def view(self):
        return self.array[:self.level]

    def __getitem__(self, idx):
        return self.array[:self.level][idx]

    def copy_from(self, a):
        self.level = len(a)
        self.array[:self.level] = a

    def pad(self, v, size):
        print(f'pad {size-self.level} codes')
        self.array[self.level:size] = v
        self.level = size

    def reset(self):
        self.level = 0
