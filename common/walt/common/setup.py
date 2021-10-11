import sys
from pathlib import Path
from typing import ClassVar

from pkg_resources import resource_stream
from plumbum import cli

from walt.common import systemd, busybox_init
from walt.common.systemd import SYSTEMD_DEFAULT_DIR


class WaltGenericSetup(cli.Application):
    # Abstract class attribute
    package: ClassVar[str]
    # Instance attributes
    _init_system = None
    _install_prefix = None
    _systemd_dir: Path = SYSTEMD_DEFAULT_DIR

    @property
    def display_name(self) -> str:
        """The name of the device that class is setting up."""
        raise NotImplementedError

    def _assert_init_is(self, expected_init_systems):
        if self._init_system not in expected_init_systems:
            fmt_init = "without init system" if self._init_system is None \
                else f"with {self._init_system!r} init system"
            sys.exit(f"Setting up a {self.display_name} {fmt_init} "
                     f"is not implemented. Exiting.")

    def setup_systemd_services(self, systemd_services):
        self._assert_init_is({"SYSTEMD", None})
        for service, options in systemd_services.items():
            service_file_content = resource_stream(self.package, service)
            systemd.install_unit(service, service_file_content,
                                 install_prefix=self._install_prefix,
                                 systemd_dir=self._systemd_dir)
            try:
                wanted_by = options['WantedBy']
            except LookupError:
                pass  # By default, do not enable unit
            else:
                systemd.enable_unit(service, wanted_by,
                                    install_prefix = self._install_prefix,
                                    systemd_dir = self._systemd_dir)

    def setup_busybox_init_services(self, busybox_services):
        self._assert_init_is({"BUSYBOX", None})
        for service in busybox_services:
            service_file_content = resource_stream(self.package, service)
            busybox_init.install_service(service, service_file_content, self._install_prefix)

    @cli.switch("--init-system", cli.Set('SYSTEMD', 'BUSYBOX', case_sensitive=False), mandatory=False)
    def set_init_system(self, init_system):
        """indicate the init system available on this device"""
        self._init_system = init_system.upper()

    @cli.switch("--prefix", Path)
    def set_install_prefix(self, _install_prefix):
        """installation prefix"""
        self._install_prefix = _install_prefix

    @cli.switch("--systemd-dir", Path)
    def set_systemd_dir(self, systemd_dir):
        """directory where to store systemd services"""
        self._systemd_dir = systemd_dir
