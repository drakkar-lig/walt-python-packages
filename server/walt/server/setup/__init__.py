from pathlib import Path

from plumbum import cli

from walt.server.setup.systemd import SYSTEMD_DEFAULT_DIR, setup_systemd


class WalTServerSetup(cli.Application):
    systemd_dir = SYSTEMD_DEFAULT_DIR

    def main(self):
        """install walt-server software"""
        setup_systemd(self.systemd_dir)

    @cli.switch("--systemd-dir", Path)
    def set_systemd_dir(self, systemd_dir):
        """directory where to store systemd services"""
        self.systemd_dir = systemd_dir
