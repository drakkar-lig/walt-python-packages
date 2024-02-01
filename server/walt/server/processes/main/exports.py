from walt.common.tools import failsafe_makedirs
from walt.server.processes.main.network import nbfs
from walt.server.processes.main.network.nfs import NFSExporter
from walt.server.processes.main.workflow import Workflow
from walt.server.tools import get_walt_subnet

PERSISTENT_PATH = "/var/lib/walt/nodes/%(node_mac)s/persist_dir"


class FilesystemsExporter:
    def __init__(self, evloop, db):
        self.nfs = NFSExporter(evloop)
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

    def get_persist_exports_info(self, nodes):
        # compute persistent node directories
        persist_paths = []
        for node in nodes:
            persist_path = PERSISTENT_PATH % dict(node_mac=node.mac)
            # ensure directory exists
            failsafe_makedirs(persist_path)
            persist_paths.append(persist_path)
        return persist_paths

    def wf_update_image_exports(self, wf, images_info, **env):
        subnet = get_walt_subnet()
        root_paths = self.get_image_exports_info(images_info)
        root_paths = list(root_paths.items())
        self.nbfs.update_image_exports(root_paths, subnet)
        wf.update_env(root_paths=root_paths, subnet=subnet)
        wf.insert_steps([self.nfs.wf_update_image_exports])
        wf.next()

    def wf_update_persist_exports(self, wf, cleanup=False, **env):
        subnet = get_walt_subnet()
        if cleanup:
            nodes = []
        else:
            nodes = self.db.select("nodes")
        persist_paths = self.get_persist_exports_info(nodes)
        wf.update_env(persist_paths=persist_paths, subnet=subnet)
        wf.insert_steps([self.nfs.wf_update_persist_exports])
        wf.next()

    def update_persist_exports(self, cleanup=False):
        wf = Workflow(
            [self.wf_update_persist_exports], cleanup=cleanup
        )
        wf.run()
