import os

class Filesystem:
    def __init__(self):
        self.exposed_get_file_type = self.get_file_type
    def get_file_type(self, path):
        if not os.path.exists(path):
            return None
        if os.path.isfile(path):
            return 'f'
        if os.path.isdir(path):
            return 'd'
        return 'o'
