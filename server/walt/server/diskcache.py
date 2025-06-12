import base64
import fcntl
import pickle
from contextlib import contextmanager
from pathlib import Path

DISK_CACHE_FILE = Path("/var/cache/walt/diskcache.pickle")
DISK_CACHE_LOCK_D = Path("/var/cache/walt/diskcache.lock.d")
OBSOLETE_SNMP_CACHE_FILE = Path("/var/cache/walt/snmp.variants")


class DiskCache:
    def __init__(self):
        self._cache = None

    def get(self, key, compute_func=None):
        if self._cache is not None:
            value = self._cache.get(key, None)
            if value is not None:
                return value
        # try to reload the cache, someone else
        # may have filled this value in
        self._load()
        value = self._cache.get(key, None)
        if value is not None:
            return value
        # we have to compute this value, but if several processes
        # want this same value, ensure only one computes it
        lock_key = base64.b64encode(pickle.dumps(key)).decode()
        with self._lock(lock_key):
            # someone else may have updated the value while we
            # were locked on lock_key
            self._load()
            value = self._cache.get(key, None)
            if value is not None:
                return value
            if compute_func is None:
                return None
            # no, so we really have to compute it
            value = compute_func()
            self._cache[key] = value
            self._save()
            return value

    def save(self, key, value):
        compute_func = lambda: value
        self.get(key, compute_func)

    @contextmanager
    def _lock(self, lock_key):
        DISK_CACHE_LOCK_D.mkdir(parents=True, exist_ok=True)
        lock_file = DISK_CACHE_LOCK_D / lock_key
        lock_file.touch()
        with lock_file.open() as fd:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
            fcntl.flock(fd, fcntl.LOCK_UN)

    def _load(self):
        with self._lock("__cache_file__"):
            if DISK_CACHE_FILE.exists():
                self._cache = pickle.loads(DISK_CACHE_FILE.read_bytes())
            elif OBSOLETE_SNMP_CACHE_FILE.exists():
                # if the obsolete cache file dedicated to snmp is present,
                # convert the values it contains to the new format, remove it and
                # rewrite the new cache file.
                self._cache = {}
                variants_cache = pickle.loads(OBSOLETE_SNMP_CACHE_FILE.read_bytes())
                for k, v in variants_cache.items():
                    new_k = ('snmp-variant',) + k
                    if new_k not in self._cache:
                        self._cache[new_k] = v
                OBSOLETE_SNMP_CACHE_FILE.unlink()
                DISK_CACHE_FILE.write_bytes(pickle.dumps(self._cache))
            else:
                self._cache = {}

    def _save(self):
        with self._lock("__cache_file__"):
            DISK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            DISK_CACHE_FILE.write_bytes(pickle.dumps(self._cache))


DISK_CACHE = DiskCache()
