from walt.client.apiobject.base import APIObjectBase
from walt.client.apiobject.nodes import get_nodes
from walt.client.apiobject.images import get_images

class APIRoot:
    def __new__(cls):
        class APIRootImpl(APIObjectBase):
            "WALT API root"
            @property
            def nodes(self):
                return get_nodes()
            @property
            def images(self):
                return get_images()
            def _close(self):
                pass
        return APIRootImpl()
