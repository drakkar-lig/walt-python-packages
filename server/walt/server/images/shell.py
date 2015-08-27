import uuid
from walt.server.images.image import parse_image_fullname

# About terminology: See comment about it in image.py.

class ModifySession(object):
    NAME_OK             = 0
    NAME_NOT_OK         = 1
    NAME_NEEDS_CONFIRM  = 2
    exposed_NAME_OK             = NAME_OK
    exposed_NAME_NOT_OK         = NAME_NOT_OK
    exposed_NAME_NEEDS_CONFIRM  = NAME_NEEDS_CONFIRM
    def __init__(self, requester, image_fullname, repo):
        self.requester = requester
        self.image_fullname, dummy1, dummy2, self.image_tag = \
            parse_image_fullname(image_fullname)
        self.new_image_tag = None
        self.repo = repo
        self.container_name = str(uuid.uuid4())
        self.repo.register_modify_session(self)
        # expose methods to the RPyC client
        self.exposed___enter__ = self.__enter__
        self.exposed___exit__ = self.__exit__
        self.exposed_get_parameters = self.get_parameters
        self.exposed_get_default_new_name = self.get_default_new_name
        self.exposed_validate_new_name = self.validate_new_name
        self.exposed_select_new_name = self.select_new_name
    def __enter__(self):
        return self
    def __exit__(self, type, value, traceback):
        self.repo.finalize_modify(self)
    def get_parameters(self):
        # return an immutable object (a tuple, not a dict)
        # otherwise we will cause other RPyC calls
        return self.image_fullname, self.container_name
    def get_default_new_name(self):
        return self.repo.get_default_new_image_tag(
            self.requester,
            self.image_tag
        )
    def validate_new_name(self, new_image_tag):
        return self.repo.validate_new_image_tag(
            self.requester,
            self.image_tag,
            new_image_tag
        )
    def select_new_name(self, new_image_tag):
        self.new_image_tag = new_image_tag

