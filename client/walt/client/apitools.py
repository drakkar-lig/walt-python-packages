
from contextlib import contextmanager

@contextmanager
def silent_server_link():
    from walt.client.link import ClientToServerLink
    from walt.common.tools import SilentBusyIndicator
    indicator = SilentBusyIndicator()
    with ClientToServerLink(busy_indicator = indicator) as server:
        server.set_config(client_type = 'api')
        yield server
