from pathlib import Path

from plumbum import cli

from .systemd import SYSTEMD_DEFAULT_DIR, setup_systemd


class WaltNodeSetup(cli.Application):
    systemd_dir = SYSTEMD_DEFAULT_DIR

    def main(self):
        """install walt-node software"""
        setup_systemd(self.systemd_dir)

    @cli.switch("--systemd-dir", Path)
    def set_systemd_dir(self, systemd_dir):
        """directory where to store systemd services"""
        self.systemd_dir = systemd_dir
