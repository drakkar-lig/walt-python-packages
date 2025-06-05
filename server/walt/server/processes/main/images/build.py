from __future__ import annotations

import typing

from walt.server.processes.main.workflow import Workflow
from walt.server.processes.main.transfer import format_node_diff_dump_command

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

    def _run_image_build_from_cmd(self, requester, task, cmd):
        task.set_async()

        def cb(retcode):
            task.return_result(retcode == 0)  # unblock client and return status

        self.blocking.run_shell_cmd(
            requester, cb, cmd, shell=False, pipe_outstreams=True
        )

    def run_image_build_from_url(self, requester, task):
        url, subdir = self.info["url"], self.info.get("subdir", "")
        username = self.info["username"]
        options = f"--from-url {url}"
        if len(subdir) > 0:
            options = f'{options} --sub-dir "{subdir}"'
        cmd = (f"walt-image-build-helper {options} "
               f"{username} {self.image_fullname}")
        self._run_image_build_from_cmd(requester, task, cmd)

    def run_image_build_from_node_diff(self, requester, server, task):
        node_name = self.info["node_name"]
        username = self.info["username"]
        node = server.nodes.get_node_info(requester, node_name)
        if node is None:
            return False
        node_diff_dump_cmd = format_node_diff_dump_command(node.ip)
        self._run_image_build_from_cmd(requester, task, [
                                       "walt-image-build-helper",
                                       "--from-node-diff",
                                       node_diff_dump_cmd,
                                       node.image,
                                       username,
                                       self.image_fullname ])

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
        wf.next()
