from walt.common.api import api, api_expose_method
from walt.server.processes.main.apisession import APISession

# Node -> Server API (thus the name NSAPI)
# Provides remote calls performed from a node to the server.


@api
class NSAPI(APISession):
    @api_expose_method
    def sync_clock(self, context):
        context.nodes.clock.sync(context.task)
