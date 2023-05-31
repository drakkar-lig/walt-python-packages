import os
from os.path import expanduser

from walt.common.version import __version__


def early_startup():
    if "PY_SLOW_DISK_PREFIX" not in os.environ:
        os.environ["PY_SLOW_DISK_PREFIX"] = expanduser("~")
    if "PY_CACHE_PREFIX" not in os.environ:
        user = os.getlogin()
        os.environ["PY_CACHE_PREFIX"] = (
            f"/tmp/{user}/walt_client_py_cache/{__version__}"
        )
