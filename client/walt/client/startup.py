
from walt.common.version import __version__
from walt.client.apiobject.root import APIRoot
from walt.client.timeout import timeout_init_handler

timeout_init_handler()
api = APIRoot()

__all__ = [ '__version__', 'api' ]
