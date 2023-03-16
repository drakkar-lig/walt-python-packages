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
            def _close(self):
                pass
        return APIRootImpl()
