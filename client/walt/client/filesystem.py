import os
from walt.common.api import api, api_expose_method

@api
class Filesystem:
    @api_expose_method
    def get_file_type(self, path):
        if not os.path.exists(path):
            return None
        if os.path.isfile(path):
            return 'f'
        if os.path.isdir(path):
            return 'd'
        return 'o'
