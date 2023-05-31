from walt.client.apiobject.base import APIObjectBase


class APIRoot:
    def __new__(cls):
        class APIRootImpl(APIObjectBase):
            "WALT API root"

            @property
            def nodes(self):
                from walt.client.apiobject.nodes import get_api_nodes_submodule

                return get_api_nodes_submodule()

            @property
            def images(self):
                from walt.client.apiobject.images import get_api_images_submodule

                return get_api_images_submodule()

            @property
            def logs(self):
                from walt.client.apiobject.logs import get_api_logs_submodule

                return get_api_logs_submodule()

            @property
            def tools(self):
                from walt.client.apiobject.tools import get_api_tools_submodule

                return get_api_tools_submodule()

            def _close(self):
                pass

        return APIRootImpl()
