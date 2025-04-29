import functools
from pathlib import Path

from walt.server.processes.main.network import nbfs
from walt.server.processes.main.network.nfs import NFSExporter
from walt.server.processes.main.workflow import Workflow
from walt.server.tools import get_walt_subnet

SQL_NODES_PERSIST_PATHS = f"""
SELECT (
    '/var/lib/walt/nodes/' || n.mac || '/persist_dirs/' || split_part(n.image, '/', 1)
) as persist_path
FROM nodes n
"""


def mkdir_multi(paths):
    mkdir = functools.partial(Path.mkdir, parents=True, exist_ok=True)
    list(map(mkdir, map(Path, paths)))


class FilesystemsExporter:
    def __init__(self, db):
        self.nfs = NFSExporter()
        self.nbfs = nbfs
        self.db = db

    def get_fsid(self, image_id):
        return image_id[:32]  # 32 first characters

    def get_image_exports_info(self, images_info):
        # compute the root filesystems of given images
        return {
            mount_path: self.get_fsid(image_id)
            for (image_id, mount_path) in images_info
        }

    def wf_update_image_exports(self, wf, images_info, **env):
        subnet = get_walt_subnet()
        root_paths = self.get_image_exports_info(images_info)
        root_paths = list(root_paths.items())
        self.nbfs.update_image_exports(root_paths, subnet)
        wf.update_env(root_paths=root_paths, subnet=subnet)
        wf.insert_steps([self.nfs.wf_update_image_exports])
        wf.next()

    def wf_update_persist_exports(self, wf, cleanup=False, **env):
        if cleanup:
            persist_paths = []
        else:
            info = self.db.execute(SQL_NODES_PERSIST_PATHS)
            persist_paths = info.persist_path.astype(str)
            mkdir_multi(persist_paths)
        wf.update_env(persist_paths=persist_paths)
        wf.insert_steps([self.nfs.wf_update_persist_exports])
        wf.next()

    def update_persist_exports(self, cleanup=False, **env):
        wf = Workflow(
            [self.wf_update_persist_exports],
            cleanup=cleanup,
            **env
        )
        wf.run()
