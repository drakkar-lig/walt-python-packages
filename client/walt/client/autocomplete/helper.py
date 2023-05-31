"""
WalT client shell autocompletion helper.
"""
import sys

from walt.client.config import conf
from walt.client.link import ClientToServerLink
from walt.client.plugins import get_hook
from walt.client.timeout import start_timeout

AUTOCOMPLETE_TIMEOUT = 4


def ac_helper():
    debug = sys.argv[1] == "--debug"
    if debug:
        other_argv = sys.argv[2:]
        from time import time

        t0 = time()
    else:
        other_argv = sys.argv[1:]
    try:
        if not debug:
            start_timeout(AUTOCOMPLETE_TIMEOUT)
        plugin_shell_autocomplete = get_hook("shell_completion_hook")
        result = None
        # check if plugin can handle autocompletion
        if plugin_shell_autocomplete is not None:
            result = plugin_shell_autocomplete(other_argv)
        # otherwise request the server to do it
        if result is None:
            with ClientToServerLink() as server:
                result = server.shell_autocomplete(
                    conf.walt.username, other_argv, debug=debug
                )
        if debug:
            print(f"delay: {time()-t0:.2}s")
        # if still None, there was an issue
        if result is None:
            sys.exit(1)  # error
        print(result)
    except Exception:
        if debug:
            raise
        sys.exit(1)  # error
