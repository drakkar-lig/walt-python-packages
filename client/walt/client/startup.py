import platform
import sys

help_url = "https://walt.readthedocs.io/en/latest/client-install.html"
if platform.system() == "Windows":
    print("Sorry walt client software cannot run directly on Windows.")
    print("Use WSL (Windows Subsystem for Linux) instead.")
    print(f"See: {help_url}")
    sys.exit(1)

from walt.client.apiobject.root import APIRoot
from walt.client.timeout import timeout_init_handler
from walt.common.version import __version__

timeout_init_handler()
api = APIRoot()

__all__ = ["__version__", "api"]
