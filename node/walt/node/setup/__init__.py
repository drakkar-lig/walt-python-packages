import sys
from pathlib import Path
from walt.common.setup import WaltGenericSetup


class WaltNodeSetup(WaltGenericSetup):
    package = __name__

    @property
    def display_name(self):
        return "WalT node"

    def main(self):
        """install WalT node software"""
        self.setup_systemd_services(["walt-logs.service"])
        self.setup_command_symlinks()


def run():
    assert (
            Path(sys.prefix) / "bin" / "activate"
        ).exists(), "walt-node seems not installed in a virtual environment"
    WaltNodeSetup.run()
