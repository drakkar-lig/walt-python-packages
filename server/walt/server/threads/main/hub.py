from walt.server.threads.main.apisession import APISession
from walt.common.thread import RPCThreadConnector
from walt.server.threads.main.api.cs import CSAPI
from walt.server.threads.main.api.ns import NSAPI
from walt.server.threads.main.api.vs import VSAPI
from walt.server.threads.main.api.ss import SSAPI

class ServiceToHubThread(object):
    def __init__(self, hub_rpc, server):
        self.hub_rpc = hub_rpc
        self.server = server
    def create_session(self, rpc_context, target_api, remote_ip):
        return APISession.create(
            self.server, target_api, remote_ip)
    def destroy_session(self, rpc_context, session_id):
        APISession.destroy(session_id)
    def run_task(self, rpc_context, session_id, attr, args, kwargs):
        session = APISession.get(session_id)
        session.run_task(rpc_context, attr, args, kwargs)

class HubRPCThreadConnector(RPCThreadConnector):
    def __init__(self, server):
        service = ServiceToHubThread(self, server)
        RPCThreadConnector.__init__(self, service)

APISession.register_target_api('NSAPI', NSAPI)
APISession.register_target_api('VSAPI', VSAPI)
APISession.register_target_api('CSAPI', CSAPI)
APISession.register_target_api('SSAPI', SSAPI)

