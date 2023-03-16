from __future__ import annotations

import typing
import uuid

from walt.common.tools import parse_image_fullname

if typing.TYPE_CHECKING:
    from walt.server.processes.main.images.image import NodeImage
    from walt.server.processes.main.images.store import NodeImageStore

# About terminology: See comment about it in image.py.
class ImageBuildSession(object):

    def __init__(self, blocking, store: NodeImageStore, image_fullname: str,
                       image_overwrite: bool, **info):
        self.blocking = blocking
        self.store = store
        self.repository = store.repository
        self.image_fullname = image_fullname
        self.image_overwrite = image_overwrite
        self.info = info

    def get_parameters(self):
        return dict(
            image_fullname = self.image_fullname,
            image_overwrite = self.image_overwrite,
            **self.info
        )

    def run_image_build_from_url(self, requester, task):
        cmd = f'walt-image-build-helper --from-url {self.info["url"]} {self.image_fullname}'
        task.set_async()
        def cb(retcode):
            task.return_result(retcode == 0)    # unblock client and return status
        self.blocking.run_shell_cmd(requester, cb, cmd, shell=False, pipe_outstreams=True)

    def finalize_image_build_session(self, requester, server, task):
        self.repository.refresh_cache_for_image(self.image_fullname)
        self.store.resync_from_repository()
        self.store.update_image_mounts()
        if self.image_overwrite:
            task.set_async()
            server.reboot_nodes_after_image_change(
                    requester, task.return_result, self.image_fullname)
