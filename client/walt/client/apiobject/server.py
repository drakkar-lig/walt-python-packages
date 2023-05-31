from walt.client.apiobject.base import APIObjectBase
from walt.client.apitools import silent_server_link


class APIServer(APIObjectBase):
    "walt server"

    def __init__(self):
        super().__init__()
        self._info = None

    def __get_remote_info__(self):
        if self._info is None:
            from walt.common.version import __version__

            with silent_server_link() as server:
                info = server.get_device_info("walt-server")
                self._info = dict(
                    ip=info["ip"],
                    mac=info["mac"],
                    device_type="server",
                    walt_version=__version__,
                )
        return self._info


class APIServerFactory:
    __instance__ = None

    @staticmethod
    def create():
        if APIServerFactory.__instance__ is None:
            APIServerFactory.__instance__ = APIServer()
        return APIServerFactory.__instance__
