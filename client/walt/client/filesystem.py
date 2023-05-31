import glob
import os
from pathlib import Path

from walt.common.api import api, api_expose_method


@api
class Filesystem:
    @api_expose_method
    def get_file_type(self, path):
        if not os.path.exists(path):
            return None
        if os.path.isfile(path):
            return "f"
        if os.path.isdir(path):
            return "d"
        return "o"

    @api_expose_method
    def get_completions(self, partial_path):
        """complete a partial path"""
        paths = glob.glob(f"{partial_path}*")
        # add a trailing slash to directories
        fixed_paths = []
        for path in paths:
            p = Path(path)
            if p.is_dir():
                path += "/"
            fixed_paths.append(path)
        return tuple(fixed_paths)
