from walt.common.tcp import Requests
from walt.server.nodes.register import NodeRegistrationHandler

class NodesManager(object):
    def __init__(self, tcp_server, **kwargs):
        self.kwargs = kwargs
        self.current_register_requests = set()
        tcp_server.register_listener_class(
                    req_id = Requests.REQ_REGISTER_NODE,
                    cls = NodeRegistrationHandler,
                    current_requests = self.current_register_requests,
                    **self.kwargs)

