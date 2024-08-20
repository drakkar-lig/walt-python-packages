#!/usr/bin/env python
# isort: skip_file
"""
WalT (wireless testbed) control tool.
"""
import sys

# run early startup hooks as soon as possible
from walt.client.plugins import run_hook_if_any

run_hook_if_any("early_startup")

# run speedup code before importing the other modules
import walt.client.speedup  # noqa: F401 E402

# import remaining modules
from walt.client.application import WalTToolboxApplication  # noqa: E402
from walt.client.plugins import add_all_categories, add_category  # noqa: E402
from walt.client.wrap import wrap_client_command  # noqa: E402
from walt.common.version import __version__  # noqa: E402

WALT_COMMAND_HELP_PREFIX = f"""\

WalT platform control tool.
Version: {__version__}

Usage:
    walt CATEGORY SUBCOMMAND [args...]

Help about a given category or subcommand:
    walt CATEGORY --help
    walt CATEGORY SUBCOMMAND --help

Help about WalT in general:
    walt help show

Categories:
"""


class WalT(WalTToolboxApplication):
    """WalT platform control tool."""

    def get_help_prefix(self):
        # for performance, only import this when needed
        from walt.client.logo import try_add_logo

        return try_add_logo(WALT_COMMAND_HELP_PREFIX)


@wrap_client_command
def run():
    # optimize loading time by adding only the category specified, when possible
    # excluded cases:
    # - user just typed 'walt'
    # - user typed 'walt advanced dump-bash-autocomplete'
    # - user typed 'walt <missing-category> [...]'
    if (
        len(sys.argv) == 1
        or tuple(sys.argv[1:3]) == ("advanced", "dump-bash-autocomplete")
        or tuple(sys.argv[1:3]) == ("advanced", "dump-zsh-autocomplete")
        or add_category(WalT, sys.argv[1]) is False
    ):
        add_all_categories(WalT)
    WalT.run()


if __name__ == "__main__":
    # about management of return code: see wrap.py
    run()
