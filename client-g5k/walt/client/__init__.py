# walt.client is a "namespace package", shared by walt-client & walt-client-g5k
# note: content must be exactly the same in these __init__.py files
__path__ = __import__('pkgutil').extend_path(__path__, __name__)
from walt.common.version import __version__