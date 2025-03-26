from walt.common.api import api, api_expose_method
from walt.server.processes.main.apisession import APISession
from walt.server.tools import np_record_to_dict

# Virtual component -> Server API (thus the name VSAPI)
# Provides remote calls performed from a virtual component to the server.


@api
class VSAPI(APISession):
    @api_expose_method
    def register_device(self, context, *args):
        context.server.add_or_update_device(*args)

    @api_expose_method
    def get_device_info(self, context, device_mac):
        return np_record_to_dict(
                context.server.devices.get_device_info(
                    requester=None, mac=device_mac))
