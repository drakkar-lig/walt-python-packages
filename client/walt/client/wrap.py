import socket
import sys

from walt.client.plugins import get_hook
from walt.common.apilink import LinkException


def wrap_client_command(f):
    def wrapped(*args, **kwargs):
        try:
            # note: plumbum.cli applications end by calling sys.exit(<retcode>).
            # Here, by convention, when main() function returns False it means
            # "failure", but sys.exit(False) translates to a return code int(False)
            # which leads to a call equivalent to sys.exit(0) (i.e. success).
            # So we detect this case and replace False by 1.
            # Similarly, we replace True by 0.
            try:
                f(*args, **kwargs)
            except SystemExit as e:
                if e.code is False:
                    sys.exit(1)
                elif e.code is True:
                    sys.exit(0)
                else:
                    raise e
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
