from walt.client.apiobject.base import APIObjectBase


class APIToolsSubModule(APIObjectBase):
    """Misc API features"""

    def get_server(self):
        """Return an API object describing the server"""
        from walt.client.apiobject.server import APIServerFactory

        return APIServerFactory.create()


def get_api_tools_submodule():
    return APIToolsSubModule()
