import sys
from walt.client.g5k.deploy.status import get_deployment_status, get_expiry_message, \
                                          save_deployment_status
from walt.client.g5k.reboot import G5KClientHardRebootHook

DEFAULT_IMAGE_NAME = 'pc-x86-64-default'

def config_missing_server_hook():
    print("No WalT platform is deployed. Use 'walt g5k deploy' first.")
    sys.exit(1)

def failing_server_socket_hook():
    info = get_deployment_status(allow_expired = True)
    if info is None:
        print("No WalT platform is deployed. Use 'walt g5k deploy' first.")
        sys.exit(1)
    if info['status'] == 'expired':
        print(get_expiry_message(info))
        sys.exit(1)
    if info['status'] != 'ready':
        print("Deployment of WalT platform is not complete yet. Use 'walt g5k wait'.")
        sys.exit(1)
    return  # if we are here, this is a real issue, let the caller handle it

def connection_hook(link, server):
    info = get_deployment_status()
    if not info.get('got_first_user_api_connection', False):
        # gain possession of nodes by associating them to our copy of their
        # default image (note: no need to reboot them because this is another
        # tag of the same image)
        link.set_busy_label("Associating nodes to your default image")
        info['got_first_user_api_connection'] = True
        save_deployment_status(info)
        link.set_silent(True)
        server.set_image('all-nodes', DEFAULT_IMAGE_NAME)
        link.set_silent(False)

class G5KPlugin:
    # name to use when running pip install walt-client[<name>]
    client_feature_name = "g5k"
    # hook methods
    hooks = {
        'config_missing_server': config_missing_server_hook,
        'failing_server_socket': failing_server_socket_hook,
        'client_hard_reboot': G5KClientHardRebootHook,
        'connection_hook': connection_hook
    }
