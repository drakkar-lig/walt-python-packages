from walt.client.apiobject.root import APIRoot
from walt.client.timeout import timeout_init_handler
from walt.common.version import __version__

timeout_init_handler()
api = APIRoot()

__all__ = ["__version__", "api"]
