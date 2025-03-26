from walt.common.api import api, api_expose_method
from walt.server.processes.main.apisession import APISession

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
        context.server.add_or_update_device(*args)

    @api_expose_method
    def web_api_v1_nodes(self, context, *args):
        return context.nodes.web_api_list_nodes("v1", *args)

    @api_expose_method
    def web_api_v1_images(self, context, *args):
        return context.images.web_api_list_images("v1", *args)

    @api_expose_method
    def get_vpn_auth_keys(self, context):
        return context.server.db.get_vpn_auth_keys()

    @api_expose_method
    def revoke_vpn_auth_key(self, context, cert_id):
        return context.server.vpn.revoke_vpn_auth_key(cert_id)
