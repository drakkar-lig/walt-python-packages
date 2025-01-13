from walt.common.formatting import format_sentence
from walt.server.processes.blocking.registries import (
    get_registry_clients,
    MissingRegistryCredentials,
)


def pull_image(requester, server, image_fullname):
    failed, issues = [], []
    clients = get_registry_clients()
    for label, client in clients:
        if (
            requester is None
            and client.auth == "basic"
            and "pull" not in client.anonymous_operations
        ):
            issues.append(
                f"Registry '{label}' does not allow anonymous pulls, ignored."
            )
            continue
        try:
            client.pull(requester, server, image_fullname)
            return ('OK',)
        except MissingRegistryCredentials as e:
            return ('MISSING_REGISTRY_CREDENTIALS', e.registry_label)
        except Exception:
            failed.append(f"'{label}'")
    # if we are here, then nothing worked
    if len(failed) > 0:
        issues.append(
            format_sentence(
                f"Failed to download {image_fullname} from %s.",
                failed,
                None,
                "registry",
                "registries",
                list_type="or",
            )
        )
    return ('FAILED', "\n".join(issues))
