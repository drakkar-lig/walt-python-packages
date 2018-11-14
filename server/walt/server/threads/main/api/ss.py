from walt.common.api import api, api_expose_method
from walt.server.threads.main.apisession import APISession

# Server -> Server API (thus the name SSAPI)
# Provides remote calls performed from one server executable
# to another one.
# For instance walt-dhcp-event sends requests to walt-server-daemon
# when a new DHCP address is assigned.
# Note that since both executables belong to the server code,
# API versioning is not relevant here. But for clarity we use
# the same decorators as for the other APIs.

@api
class SSAPI(APISession):

    @api_expose_method
    def register_device(self, context, *args):
        context.server.register_device(*args)
