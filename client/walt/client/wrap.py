import sys, socket
from walt.common.apilink import LinkException
from walt.client.plugins import get_hook
from walt.client.timeout import timeout_init_handler

def wrap_client_command(f):
    def wrapped(*args, **kwargs):
        try:
            timeout_init_handler()
            f(*args, **kwargs)
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
    return wrapped
