from walt.client.apiobject.base import APIObjectBase, APIObjectRegistry, CommentedString
from walt.client.apitools import snakecase, create_names_dict
from walt.client.link import ClientToServerLink
from walt.client.config import conf
from walt.client.timeout import start_timeout, stop_timeout
from walt.common.tools import SilentBusyIndicator
from contextlib import contextmanager

@contextmanager
def silent_server_link():
    indicator = SilentBusyIndicator()
    with ClientToServerLink(busy_indicator = indicator) as server:
        yield server

class APIImage:
    _known = {}
    _deleted = set()
    def __new__(cls, image_name):
        def check_deleted():
            if image_name in APIImage._deleted:
                raise ReferenceError('This image is no longer valid! (was removed)')
        if image_name not in APIImage._known:
            class APIImageImpl(APIObjectBase):
                __doc__ = f"image {image_name}"
                def __get_remote_info__(self):
                    check_deleted()
                    info = { "name": image_name,
                             "ready": "unknown -- TODO"
                           }
                    return info
                def remove(self):
                    """Remove this image"""
                    with silent_server_link() as server:
                        server.remove_image(image_name)
                        APIImage._deleted.add(image_name)
            APIImage._known[image_name] = APIImageImpl()
        return APIImage._known[image_name]

def get_images():
    with silent_server_link() as server:
        names = server.show_images(conf.walt.username, refresh=False, names_only=True)
    d = create_names_dict(
        ((name, APIImage(name)) \
         for name in names.splitlines()),
        name_format = snakecase
    )
    return APIObjectRegistry(d, 'Set of WalT images')
