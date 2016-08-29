from walt.common.api import api, api_expose_method

@api
class NSAPI(object):

    def __init__(self, devices, nodes):
        self.devices = devices
        self.nodes = nodes
        self.remote_ip = None

    @api_expose_method
    def node_bootup_event(self):
        self.devices.node_bootup_event(self.remote_ip)
        node_name = self.devices.get_name_from_ip(self.remote_ip)
        self.nodes.node_bootup_event(node_name)

