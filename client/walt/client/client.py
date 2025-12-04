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

WALT_COMMAND_HELP_PREFIX = """\

TOOL

STATUS_BOX

Usage:
    walt CATEGORY SUBCOMMAND [args...]

Help about a given category or subcommand:
    walt CATEGORY --help
    walt CATEGORY SUBCOMMAND --help

Help about WalT in general:
    walt help show

Categories:
"""

STATUS_BOX = f"""\
   Version: {__version__}
    Server: SERVER
Completion: COMP_STATUS
"""


class WalT(WalTToolboxApplication):
    """WalT platform control tool."""

    def get_help_prefix(self):
        # for performance, only import this when needed
        import os
        from walt.client.logo import try_add_logo
        from walt.common.formatting import framed, highlight
        from walt.client.config import conf

        comp_help = False
        completion_version = os.environ.get("_WALT_COMP_VERSION")
        if completion_version is None:
            comp_status = highlight("missing or outdated (*)")
            comp_help = True
        elif completion_version != __version__:
            comp_status = highlight("outdated (*)")
            comp_help = True
        else:
            comp_status = "up-to-date"
        box = STATUS_BOX.replace("SERVER", conf.walt.server)
        box = box.replace("COMP_STATUS", comp_status)
        box = framed("Status", box)
        if comp_help:
            box += "\n(*) see: walt help show shell-completion"
        text = WALT_COMMAND_HELP_PREFIX
        text = text.replace("TOOL",
                            highlight("WalT platform control tool."))
        text = text.replace("STATUS_BOX", box)
        return try_add_logo(text)


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
