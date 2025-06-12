from walt.common.api import api, api_expose_method
from walt.server.processes.main.apisession import APISession

# Node -> Server API (thus the name NSAPI)
# Provides remote calls performed from a node to the server.


@api
class NSAPI(APISession):
    @api_expose_method
    def sync_clock(self, context):
        context.nodes.clock.sync(context.task)

    @api_expose_method
    def report_lldp_neighbor(self, context, sw_mac, sw_port_lldp_label):
        context.server.report_lldp_neighbor(
            context.remote_ip, sw_mac, sw_port_lldp_label
        )
