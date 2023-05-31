# walt.client is a "namespace package", shared by walt-client &
# walt-client-<plugin> packages
# note: content must be exactly the same in these __init__.py files
__path__ = __import__("pkgutil").extend_path(__path__, __name__)
from walt.client.startup import *  # noqa: F401 F403
