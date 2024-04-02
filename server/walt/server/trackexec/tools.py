import numpy as np

from walt.server.trackexec.const import MAP_BLOCK_UINT16_SIZE


def _map_block_max_bytecode_size(stack_size):
    # stack_size         -- 1 uint16 large
    # stack              -- 2*<stack_size> uint16 large
    # bytecode           -- up to the MAP_BLOCK_UINT16_SIZE limit
    return MAP_BLOCK_UINT16_SIZE - ((stack_size << 1) + 1)


def map_block_dt(stack_size):
    return np.dtype([('stack_size', np.uint16),
                     ('stack', [
                         ('file_id', np.uint16),
                         ('lineno', np.uint16)
                      ], (stack_size,)),
                     ('bytecode', np.uint16, (
                         _map_block_max_bytecode_size(stack_size),))])


def index_block_dt():
    return np.dtype([('timestamp', np.uint64),
                     ('min_stack_size', np.uint16)])


class Uint16Stack:
    def __init__(self):
        self.array = np.empty(MAP_BLOCK_UINT16_SIZE, np.uint16)
        self.level = 0

    def add(self, v):
        self.array[self.level] = v
        self.level += 1

    def pop(self):
        self.level -= 1
        return self.array[self.level]

    def top(self):
        if self.level > 0:
            return self.array[self.level-1]

    def view(self):
        return self.array[:self.level]

    def __getitem__(self, idx):
        return self.array[:self.level][idx]

    def copy_from(self, a):
        self.level = len(a)
        self.array[:self.level] = a

    def pad(self, v, size):
        self.array[self.level:size] = v
        self.level = size

    def reset(self):
        self.level = 0

    def __len__(self):
        return self.level

    def copy(self):
        other = Uint16Stack()
        other.copy_from(self.array[:self.level])
        return other


class LogAbstractManagement:

    def __init__(self, dir_path):
        self._dir_path = dir_path
        self._log_index_path = dir_path / "log_index"
        self._log_sources_archive_path = dir_path / "log_sources.tar.gz"
        self._log_sources_index_gz_path = dir_path / "log_sources_index.gz"
        self._log_map_num = 0

    @property
    def _log_map_path(self):
        return self._dir_path / "log_map" / f"{self._log_map_num}"

    @property
    def _log_map_gz_path(self):
        return self._dir_path / "log_map" / f"{self._log_map_num}.gz"
