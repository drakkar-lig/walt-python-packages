from walt.common.api import api, api_expose_method
from walt.server.processes.main.apisession import APISession

# Virtual component -> Server API (thus the name VSAPI)
# Provides remote calls performed from a virtual component to the server.


@api
class VSAPI(APISession):
    @api_expose_method
    def register_device(self, context, *args):
        context.server.add_or_update_device(*args)

    @api_expose_method
    def get_device_info(self, context, device_mac):
        return context.server.get_device_info(device_mac)

    @api_expose_method
    def vpn_request_grant(self, context, device_mac):
        return context.server.vpn.request_grant(context.task, device_mac)
