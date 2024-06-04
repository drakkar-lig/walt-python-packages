"""Systemd units installation toolkit"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from walt.common.tools import failsafe_symlink

SYSTEMD_DEFAULT_DIR = Path("/etc/systemd/system")


def get_unit_file_path(unit_name: str, install_prefix: Path, systemd_dir: Path):
    """Return the file path of a systemd unit.

    :param unit_name: Full unit name (with extension).
    :param install_prefix: The root where to install units.
    :param systemd_dir: The systemd directory where to install the files.
    """
    # With an install prefix, drop systemd_dir's root if it has one to make
    # it relative to the install prefix.
    if install_prefix is None:
        install_dir = systemd_dir
    else:
        install_dir = install_prefix / systemd_dir.relative_to(systemd_dir.anchor)
    return install_dir / unit_name


def install_unit(
    unit_name: str,
    unit_content: bytes,
    install_prefix: Path = None,
    systemd_dir: Path = SYSTEMD_DEFAULT_DIR,
):
    """Install a systemd unit in the filesystem.

    :param unit_name: Full unit name (with extension).
    :param unit_content: The unit content to put in the installed file
    :param install_prefix: The root where to install units.
    :param systemd_dir: The systemd directory where to install the files.
    """
    # note: link target does not depend on install prefix
    unit_file_path = get_unit_file_path(unit_name, install_prefix, systemd_dir)
    install_dir = unit_file_path.parent
    link_target = systemd_dir / unit_name
    # write unit file
    unit_file_path.parent.mkdir(parents=True, exist_ok=True)
    unit_file_path.write_bytes(unit_content)
    # install symlink(s) if unit file as 'WantedBy=...' patterns
    # (this will enable the unit)
    for line in unit_content.splitlines():
        if line.startswith(b"WantedBy"):
            w_by = line.decode("ascii").replace("=", " ").split()[1]
            wants_path = install_dir / (w_by + ".wants") / unit_name
            wants_path.parent.mkdir(parents=True, exist_ok=True)
            failsafe_symlink(str(link_target), str(wants_path))


def disable_unit(
    unit_name: str, install_prefix: Path = None, systemd_dir: Path = SYSTEMD_DEFAULT_DIR
):
    """Disable a systemd unit in the filesystem.

    :param unit_name: Full unit name (with extension).
    :param install_prefix: The root where to install units.
    :param systemd_dir: The systemd directory where to install the files.
    """
    # some of the services we must disable are SYSV compatible scripts.
    # in this case disabling a service is a different operation.
    # thus we use "systemctl disable" in this case.
    # thanks to the --root option, systemctl operates on the file
    # system directly, instead of communicating with the systemd
    # daemon; thus this code should work in a Dockerfile RUN step too.
    if install_prefix is None:
        install_prefix = "/"
    subprocess.run(
        shlex.split(f"systemctl --root={install_prefix} disable {unit_name}"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # if the unit we just disabled was in a failed state, reset this state.
    # Note: --root option is not available in this case, so we run the
    # command without the check=True option. If we are in a Dockerfile,
    # no systemd daemon is running, so this would fail, but without
    # a daemon we do not have a running state for units anyway.
    subprocess.run(
        shlex.split(f"systemctl reset-failed {unit_name}"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def unit_exists(unit_name: str, install_prefix: Path = None):
    """Check if a systemd unit with given name exists.

    :param unit_name: Full unit name (with extension).
    :param install_prefix: The root of the OS.
    """
    if install_prefix is None:
        install_prefix = "/"
    try:
        p = subprocess.run(
            shlex.split(
                f"systemctl --root={install_prefix} list-unit-files {unit_name}"
            ),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # unfortunately older versions of systemctl (on buster) return a status
        # of zero (i.e. success) even if no unit files are found.
        # so we have to parse the ending line indicating how many unit files
        # were found.
        return int(p.stdout.splitlines()[-1].split()[0]) > 0
    except Exception:
        return False


def do_units(unit_names: list[str], action: str):
    """Do something (start, stop, etc.) on systemd units.

    :param unit_names: List of full unit names (with extension).
    :param action: Systemd command (start, stop, etc.).
    """
    for unit_name in unit_names:
        subprocess.run(
            shlex.split(f"systemctl {action} {unit_name}"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def reload():
    subprocess.run(shlex.split("systemctl daemon-reload"), check=True)
