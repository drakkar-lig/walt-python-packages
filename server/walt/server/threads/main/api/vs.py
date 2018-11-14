from walt.common.api import api, api_expose_method
from walt.server.threads.main.apisession import APISession

# Virtual component -> Server API (thus the name VSAPI)
# Provides remote calls performed from a virtual component to the server.

@api
class VSAPI(APISession):

    @api_expose_method
    def register_device(self, context, *args):
        context.server.register_device(*args)

    @api_expose_method
    def get_device_info(self, context, device_mac):
        return context.server.get_device_info(device_mac)
