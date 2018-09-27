from walt.common.api import api, api_expose_method
from walt.server.threads.main.apisession import APISession

# Node -> Server API (thus the name NSAPI)
# Provides remote calls performed from a node to the server.

@api
class NSAPI(APISession):

    @api_expose_method
    def node_bootup_event(self, context):
        node_name = context.devices.get_name_from_ip(context.remote_ip)
        context.nodes.node_bootup_event(node_name)

    @api_expose_method
    def sync_clock(self, context):
        context.nodes.clock.sync(context.task)

