import socket
import sys

from walt.client.plugins import get_hook
from walt.common.apilink import LinkException


def wrap_client_command(f):
    def wrapped(*args, **kwargs):
        # note: the conversion of the return value of main() methods
        # (False -> exit code 1, True -> exit code 0) is done in
        # walt.client.application.WalTApplication.
        try:
            f(*args, **kwargs)
        except socket.error:
            hook = get_hook("failing_server_socket")
            if hook is not None:
                hook()
            sys.exit("Network connection to WalT server failed!")
        except LinkException:
            sys.exit("Issue occured while communicating with WalT server!")
        except KeyboardInterrupt:
            print()
            sys.exit("Aborted.")

    return wrapped
