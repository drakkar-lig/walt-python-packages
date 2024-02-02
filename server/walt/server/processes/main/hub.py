from walt.server.process import RPCProcessConnector


class HubRPCProcessConnector(RPCProcessConnector):
    def __init__(self):
        RPCProcessConnector.__init__(self, label="main-to-hub")
    def configure(self, server):
        from walt.server.processes.main.services import (
                ServiceToHubProcess,
                register_apis
        )
        register_apis()
        service = ServiceToHubProcess(self, server)
        RPCProcessConnector.configure(self, service)
