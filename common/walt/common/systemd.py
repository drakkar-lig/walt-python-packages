"""Systemd units installation toolkit"""

from __future__ import annotations

import io
from pathlib import Path

from walt.common.tools import failsafe_symlink

SYSTEMD_DEFAULT_DIR = Path("/etc/systemd/system")


def install_unit(unit_name: str, unit_content: io.BytesIO,
                 install_prefix: Path = None, systemd_dir: Path = SYSTEMD_DEFAULT_DIR):
    """Install a systemd unit in the filesystem.

    :param unit_name: Full unit name (with extension).
    :param unit_content: The unit content to put in the installed file
    :param install_prefix: The root where to install units.
    :param systemd_dir: The systemd directory where to install the files.
    """
    # With an install prefix, drop systemd_dir's root if it has one to make
    # it relative to the install prefix.
    if install_prefix is None:
        install_dir = systemd_dir
    else:
        install_dir = install_prefix / systemd_dir.relative_to(systemd_dir.anchor)
    unit_file_path = install_dir / unit_name
    unit_file_path.parent.mkdir(parents=True, exist_ok=True)
    unit_file_path.write_bytes(unit_content.read())


def enable_unit(unit_name: str, wanted_by: str | list[str],
                install_prefix: Path = None, systemd_dir: Path = SYSTEMD_DEFAULT_DIR):
    """Enable a systemd unit in the filesystem.

    :param unit_name: Full unit name (with extension).
    :param wanted_by: "WantedBy" unit names, i.e. units that should activate that one.
    :param install_prefix: The root where to install units.
    :param systemd_dir: The systemd directory where to install the files.
    """
    # Compute link target first, as the link target does not depend on install
    # prefix.
    unit_file_path = systemd_dir / unit_name
    # With an install prefix, drop systemd_dir's root if it has one to make
    # it relative to the install prefix.
    if install_prefix is None:
        install_dir = systemd_dir
    else:
        install_dir = install_prefix / systemd_dir.relative_to(systemd_dir.anchor)
    # Force wanted_by to be a list
    if isinstance(wanted_by, str):
        wanted_by = [wanted_by]
    for w_by in wanted_by:
        wants_path = install_dir / (w_by + '.wants') / unit_name
        wants_path.parent.mkdir(parents=True, exist_ok=True)
        failsafe_symlink(str(unit_file_path), str(wants_path))
