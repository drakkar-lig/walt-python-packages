from contextlib import contextmanager


@contextmanager
def silent_server_link():
    from walt.client.link import ClientToServerLink
    from walt.common.tools import SilentBusyIndicator

    indicator = SilentBusyIndicator()
    with ClientToServerLink(busy_indicator=indicator) as server:
        server.set_config(client_type="api")
        yield server


def device_set_to_str(device_set):
    if hasattr(device_set, "name"):  # works for APINodeBase
        return device_set.name
    elif isinstance(device_set, str):
        return device_set
    else:
        # it may be an iterable (APISetOfNodesBase, set(), tuple(), list(), ...)
        try:
            return ",".join(device_set_to_str(device) for device in device_set)
        except TypeError:
            return None


def get_devices_names(server, device_set, allowed_device_set):
    device_set = device_set_to_str(device_set)
    if device_set is None:
        return None
    return server.parse_set_of_devices(device_set, allowed_device_set)
