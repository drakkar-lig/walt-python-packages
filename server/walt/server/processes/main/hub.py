from walt.server.process import RPCProcessConnector
from walt.server.processes.main.api.cs import CSAPI
from walt.server.processes.main.api.ns import NSAPI
from walt.server.processes.main.api.ss import SSAPI
from walt.server.processes.main.api.vs import VSAPI
from walt.server.processes.main.apisession import APISession


class ServiceToHubProcess(object):
    def __init__(self, hub_rpc, server):
        self.hub_rpc = hub_rpc
        self.server = server

    def destroy_session(self, rpc_context, session_id):
        APISession.destroy(session_id)

    def run_task(
        self, rpc_context, session_id, target_api, remote_ip, attr, args, kwargs
    ):
        session = APISession.get(self.server, session_id, target_api, remote_ip)
        return session.run_task(rpc_context, attr, args, kwargs)


class HubRPCProcessConnector(RPCProcessConnector):
    def __init__(self, server):
        service = ServiceToHubProcess(self, server)
        RPCProcessConnector.__init__(self, service, label="main-to-hub")


APISession.register_target_api("NSAPI", NSAPI)
APISession.register_target_api("VSAPI", VSAPI)
APISession.register_target_api("CSAPI", CSAPI)
APISession.register_target_api("SSAPI", SSAPI)
