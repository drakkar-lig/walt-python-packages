#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import sys, locale
# workaround plumbum i18n module loading pkg_resources, which is slow,
# unless locale starts with 'en'. we cannot blindly call setlocale()
# because we do not know which locales are available on the OS where
# walt client is installed.
locale.getlocale = lambda *args: ('en_US', 'UTF-8')

from walt.client.plugins import add_category, add_all_categories
from walt.client.logo import try_add_logo
from walt.client.application import WalTToolboxApplication
from walt.client.wrap import wrap_client_command

WALT_COMMAND_HELP_PREFIX = '''\

WalT platform control tool.

Usage:
    walt CATEGORY SUBCOMMAND [args...]

Help about a given category or subcommand:
    walt CATEGORY --help
    walt CATEGORY SUBCOMMAND --help

Help about WalT in general:
    walt help show

Categories:
'''

class WalT(WalTToolboxApplication):
    """WalT platform control tool."""
    def get_help_prefix(self):
        return try_add_logo(WALT_COMMAND_HELP_PREFIX)

@wrap_client_command
def run():
    # optimize loading time by adding only the category specified, when possible
    # excluded cases:
    # - user just typed 'walt'
    # - user typed 'walt advanced dump-bash-autocomplete'
    # - user typed 'walt <missing-category> [...]'
    if len(sys.argv) == 1 or \
       tuple(sys.argv[1:3]) == ('advanced', 'dump-bash-autocomplete') or \
       add_category(WalT, sys.argv[1]) == False:
        add_all_categories(WalT)
    WalT.run()

if __name__ == '__main__':
    run()
