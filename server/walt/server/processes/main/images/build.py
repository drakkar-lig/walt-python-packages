from __future__ import annotations

import typing

from walt.server.processes.main.workflow import Workflow

if typing.TYPE_CHECKING:
    from walt.server.processes.main.images.store import NodeImageStore


# About terminology: See comment about it in image.py.
class ImageBuildSession(object):
    def __init__(
        self,
        blocking,
        store: NodeImageStore,
        image_fullname: str,
        image_overwrite: bool,
        **info,
    ):
        self.blocking = blocking
        self.store = store
        self.registry = store.registry
        self.image_fullname = image_fullname
        self.image_overwrite = image_overwrite
        self.info = info

    def get_parameters(self):
        return dict(
            image_fullname=self.image_fullname,
            image_overwrite=self.image_overwrite,
            **self.info,
        )

    def run_image_build_from_url(self, requester, task):
        cmd = (
            "walt-image-build-helper --from-url"
            f" {self.info['url']} {self.image_fullname}"
        )
        task.set_async()

        def cb(retcode):
            task.return_result(retcode == 0)  # unblock client and return status

        self.blocking.run_shell_cmd(
            requester, cb, cmd, shell=False, pipe_outstreams=True
        )

    def finalize_image_build_session(self, requester, server, task):
        task.set_async()
        self.registry.refresh_cache_for_image(self.image_fullname)
        self.store.resync_from_registry()
        wf = Workflow(
            [
                self.store.wf_update_image_mounts,
                self.wf_reboot_nodes,
                self.wf_return_result,
            ],
            requester=requester,
            server=server,
            task=task,
        )
        wf.run()

    def wf_reboot_nodes(self, wf, requester, server, **env):
        if self.image_overwrite:
            server.reboot_nodes_after_image_change(
                requester, wf.next, self.image_fullname
            )
        else:
            wf.next("OK")

    def wf_return_result(self, wf, result, task, **env):
        task.return_result(result)
