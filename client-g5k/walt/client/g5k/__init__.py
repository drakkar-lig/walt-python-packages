from walt.common.version import __version__
from walt.client.g5k.cli import WalTG5K
from walt.client.g5k.plugin import G5KPlugin
WALT_CLIENT_CATEGORY = "g5k", WalTG5K
WALT_CLIENT_PLUGIN = G5KPlugin()
