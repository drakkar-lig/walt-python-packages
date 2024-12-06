from walt.client.apiobject.base import APIObjectBase


class APIRoot:
    def __new__(cls):
        class APIRootImpl(APIObjectBase):
            "WALT API root"

            def _check_update(self):
                from walt.client.apitools import silent_server_link
                try:
                    with silent_server_link() as server:
                        pass
                except Exception as e:
                    # module reloading breaks exception catching,
                    # so check the exception by name
                    if e.__class__.__name__ == "WalTUpdatedException":
                        pass   # ok, code was just updated
                    else:
                        raise

            @property
            def nodes(self):
                self._check_update()
                from walt.client.apiobject.nodes import get_api_nodes_submodule

                return get_api_nodes_submodule()

            @property
            def images(self):
                self._check_update()
                from walt.client.apiobject.images import get_api_images_submodule

                return get_api_images_submodule()

            @property
            def logs(self):
                self._check_update()
                from walt.client.apiobject.logs import get_api_logs_submodule

                return get_api_logs_submodule()

            @property
            def tools(self):
                self._check_update()
                from walt.client.apiobject.tools import get_api_tools_submodule

                return get_api_tools_submodule()

            def _close(self):
                pass

        return APIRootImpl()
