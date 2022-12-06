from walt.server.processes.blocking.repositories import get_registry_clients
from walt.common.formatting import format_sentence

def pull_image(server, image_fullname):
    failed = []
    clients = get_registry_clients()
    for label, client in clients:
        try:
            client.pull(server, image_fullname)
            return True,
        except:
            failed.append(f"'{label}'")
    # if we are here, then all failed
    issue = format_sentence(f"Failed to download {image_fullname} from %s.",
                    failed, None, 'registry', 'registries', list_type='or')
    return False, issue
