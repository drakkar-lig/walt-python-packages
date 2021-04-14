#!/usr/bin/env python
"""
WalT (wireless testbed) control tool.
"""
import sys, socket, locale
# workaround plumbum i18n module loading pkg_resources, which is slow,
# unless locale starts with 'en'. we cannot blindly call setlocale()
# because we do not know which locales are available on the OS where
# walt client is installed.
locale.getlocale = lambda *args: ('en_US', 'UTF-8')

from walt.client.plugins import add_category, add_all_categories, get_hook
from walt.common.apilink import LinkException
from walt.client.logo import try_add_logo
from walt.client.application import WalTToolboxApplication
from walt.client.timeout import timeout_init_handler

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

def run():
    try:
        timeout_init_handler()
        # optimize loading time by adding only the category specified, if any
        if len(sys.argv) == 1 or add_category(WalT, sys.argv[1]) == False:
            add_all_categories(WalT)
        WalT.run()
    except socket.error:
        hook = get_hook('failing_server_socket')
        if hook is not None:
            hook()
        sys.exit('Network connection to WalT server failed!')
    except LinkException:
        sys.exit('Issue occured while communicating with WalT server!')
    except KeyboardInterrupt:
        print()
        sys.exit('Aborted.')

