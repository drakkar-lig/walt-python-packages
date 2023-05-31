"""Busybox init units installation toolkit"""

from __future__ import annotations

import io
from pathlib import Path

BUSYBOX_INIT_DIR = Path("/etc/init.d")


def install_service(
    service_name: str, service_content: io.BytesIO, install_prefix: Path = None
):
    """Install a busybox-init service in the filesystem.

    :param service_name: Full service name.
    :param service_content: The service content to put in the installed file.
    :param install_prefix: The root where to install units.
    """
    # With an install prefix, drop systemd_dir's root if it has one to make
    # it relative to the install prefix.
    if install_prefix is None:
        install_dir = BUSYBOX_INIT_DIR
    else:
        install_dir = install_prefix / BUSYBOX_INIT_DIR.relative_to(
            BUSYBOX_INIT_DIR.anchor
        )
    service_file_path = install_dir / service_name
    if service_file_path.exists():
        raise FileExistsError(service_file_path)
    service_file_path.parent.mkdir(parents=True, exist_ok=True)
    service_file_path.write_bytes(service_content.read())
    service_file_path.chmod(0o755)  # executable
