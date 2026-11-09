import numpy as np

from trackexec.const import MAP_BLOCK_UINT16_SIZE, TRACE_FORMAT_VERSION


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


class TraceFormatError(Exception):
    pass


class LogAbstractManagement:

    def __init__(self, dir_path):
        self._dir_path = dir_path
        self._log_index_path = dir_path / "log_index"
        self._log_sources_archive_path = dir_path / "log_sources.tar.gz"
        self._log_sources_index_gz_path = dir_path / "log_sources_index.gz"
        self._log_map_num = 0
        self._format_version_path = dir_path / "format_version"

    def _write_format_version(self):
        self._format_version_path.write_text(f"{TRACE_FORMAT_VERSION}\n")

    def _check_format_version(self):
        if self._format_version_path.exists():
            version = int(self._format_version_path.read_text().strip())
        else:
            version = 1  # traces recorded before the file was introduced
        if version > TRACE_FORMAT_VERSION:
            raise TraceFormatError(
                f"{self._dir_path}: this trace uses format version {version}, "
                f"but this version of trackexec only supports versions up "
                f"to {TRACE_FORMAT_VERSION}; please upgrade trackexec.")

    @property
    def _log_map_path(self):
        return self._dir_path / "log_map" / f"{self._log_map_num}"

    @property
    def _log_map_gz_path(self):
        return self._dir_path / "log_map" / f"{self._log_map_num}.gz"
