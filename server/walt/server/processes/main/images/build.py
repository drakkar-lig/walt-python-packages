from __future__ import annotations

import os
import signal
from pathlib import Path

from walt.common.netsetup import NetSetup
from walt.server.const import SSH_NODE_COMMAND
from walt.server.workflow import Workflow
from walt.server.processes.main.transfer import format_node_diff_dump_command
from walt.server.processes.main.nodes.reboot import wf_reboot_nodes


class SilentStream:
    def write(self, s):
        pass


class SilentRequester:
    def __init__(self):
        self.stdout = SilentStream()
        self.stderr = self.stdout


# About terminology: See comment about it in image.py.
class ImageBuildSession(object):
    def __init__(
        self,
        server,
        image_fullname: str,
        image_overwrite: bool,
        **info,
    ):
        self.server = server
        self.blocking = server.blocking
        self.store = server.images.store
        self.registry = self.store.registry
        self.exports = server.exports
        self.image_fullname = image_fullname
        self.image_overwrite = image_overwrite
        self.info = info
        self._pid_file = None
        self._ibron_task = None
        self._ibron_wf = None
        self._ibron_orig_netsetup = None
        self._ibron_attached_node = False

    def record_session_id(self, session_id):
        self.session_id = session_id

    def get_parameters(self):
        return dict(
            session_id = self.session_id,
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
        with_node_name = self.info.get("with_node_name")
        username = self.info["username"]
        options = f"--from-url {url} --session-id {self.session_id}"
        if len(subdir) > 0:
            options += f' --sub-dir "{subdir}"'
        if with_node_name is not None:
            options += f' --with_node "{with_node_name}"'
        cmd = (f"walt-image-build-helper {options} "
               f"{username} {self.image_fullname}")
        self._run_image_build_from_cmd(requester, task, cmd)

    def run_image_build_from_node_diff(self, requester, task):
        node_name = self.info["node_name"]
        username = self.info["username"]
        node = self.server.nodes.get_node_info(requester, node_name)
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

    def finalize_image_build_session(self, requester, task):
        task.set_async()
        self.registry.refresh_cache_for_image(self.image_fullname)
        self.store.resync_from_registry()
        wf = Workflow(
            [
                self.exports.wf_update,
                self._wf_end_of_build_reboot_nodes,
                self._wf_return_result,
            ],
            requester=requester,
            task=task,
        )
        wf.run()

    def _wf_end_of_build_reboot_nodes(self, wf, requester, **env):
        if self.image_overwrite:
            self.server.reboot_nodes_after_image_change(
                requester, wf.next, self.image_fullname
            )
        else:
            wf.next("OK")

    def _wf_return_result(self, wf, result, task, **env):
        task.return_result(result)
        wf.next()

    def _ibron_get_node(self):
        node_mac = self.info["with_node_mac"]
        return self.server.devices.get_device_info(mac=node_mac)

    def image_build_run_on_node_start_workflow(self, requester, task,
                                               rootfs):
        node = self._ibron_get_node()
        task.set_async()
        # prepare workflow
        # - we start by ensuring the node is up
        #   (if it's down the user might want to know it early)
        if node.booted:
            wf_steps = []
        else:
            wf_steps = [self._wf_ibron_wait_for_node]
        # - and then do the real things
        wf_steps += [
            self._wf_ibron_ensure_netsetup_nat,
            self._wf_ibron_attach_node_to_rootfs,
            self._wf_ibron_end_phase,   # end prepare phase
            self._wf_ibron_run_command,
            self._wf_ibron_end_phase,   # end run_cmd phase
            self._wf_ibron_restore_netsetup,
            self._wf_ibron_detach_node,
            self._wf_ibron_end,
        ]
        wf = Workflow(
            wf_steps,
            requester=requester,
            rootfs=rootfs,
            node=node,
            server=self.server,
            retcode=None,
        )
        # update attributes (also useful for the cleanup procedure)
        self._ibron_task = task
        self._ibron_wf = wf
        # run the workflow
        wf.run()

    def _wf_ibron_end_phase(self, wf, retcode, **env):
        self._ibron_task.return_result(retcode)
        self._ibron_task = None
        # We pause the workflow here, so we don't call wf.next() yet.
        # It should be resumed by a call to
        # image_build_run_on_node_resume_workflow() instead.

    def image_build_run_on_node_resume_workflow(self, requester, task):
        if task is not None:
            task.set_async()
            self._ibron_task = task
        # each api call of image-build-runtime involves a new instance
        # of the "requester" object.
        self._ibron_wf.update_env(requester=requester)
        self._ibron_wf.next()

    def _wf_ibron_attach_node_to_rootfs(self, wf, requester,
                                        node, rootfs, **env):
        requester.stderr.write(
            f"Rebooting {node.name} on the intermediate image...\n")
        self.exports.set_image_build_export(node.mac, rootfs)
        wf.insert_steps([self.exports.wf_update,
                         self._wf_ibron_reboot_node,
                         self._wf_ibron_wait_for_node,
                        ])
        self._ibron_attached_node = True
        wf.next()

    def _wf_ibron_detach_node(self, wf, node, **env):
        self.exports.unset_image_build_export(node.mac)
        self._ibron_attached_node = False
        wf.insert_steps([self.exports.wf_update,
                         self._wf_ibron_reboot_node])
        wf.next()

    def _wf_ibron_ensure_netsetup_nat(self, wf, node, **env):
        orig_netsetup = NetSetup(
                    node.conf.get("netsetup", NetSetup.LAN))
        if orig_netsetup != NetSetup.NAT:
            self.server.settings.set_device_config(
                    SilentRequester(), node.name, ["netsetup=NAT"])
            self._ibron_orig_netsetup = orig_netsetup
        wf.next()

    def _wf_ibron_restore_netsetup(self, wf, node, **env):
        if self._ibron_orig_netsetup is not None:
            netsetup_label = self._ibron_orig_netsetup.name
            self.server.settings.set_device_config(
                    SilentRequester(), node.name,
                    [f"netsetup={netsetup_label}"])
            self._ibron_orig_netsetup = None
        wf.next()

    def _wf_ibron_reboot_node(self, wf, requester, node, **env):
        wf.update_env(
            nodes=[node],
            hard_only=False,
            reboot_cause="Dockerfile 'RUN --on-node <cmd>'",
            requester=None,
            saved_requester=requester,
        )
        wf.insert_steps([wf_reboot_nodes, self._wf_restore_requester])
        wf.next()

    def _wf_restore_requester(self, wf, saved_requester, **env):
        wf.update_env(requester=saved_requester)
        wf.next()

    def _wf_ibron_wait_for_node(self, wf, requester, node, **env):
        requester.stderr.write(
            f"Waiting for {node.name} to be booted...\n")
        wf.update_env(
            nodes=[node],
        )
        wf.insert_steps([self.server.nodes.wf_wait])
        wf.next()

    def _wf_ibron_run_command(self, wf, requester, node, **env):
        requester.stderr.write(
            f"Running the command on {node.name}...\n")
        ssh = SSH_NODE_COMMAND
        ip = node.ip
        wf.update_env(
            cmd=f"{ssh} root@{ip} /.run-on-node.sh",
            raise_exception=False,
            silent=False,
            pipe_stdout=requester.stdout,
            pipe_stderr=requester.stderr,
        )
        wf.insert_steps([self.server.ev_loop.wf_do])
        wf.next()

    def _wf_ibron_end(self, wf, **env):
        # let the cleanup procedure know that this image-build-run-on-node
        # workflow is no longer running
        self._ibron_wf = None
        wf.next()

    def cleanup(self):
        # note: this is called at the end of the whole build session,
        # either after a successful run or in case of user interrupt.
        # keep in mind that in the case of image-build-run-on-node,
        # it is *not* called after each "RUN --on-node <cmd>" directive!
        if self._ibron_task is not None:
            self._ibron_task.interrupt()
        if self._ibron_wf is not None:
            self._ibron_wf.interrupt()
            node = self._ibron_get_node()
            cleanup_steps = []
            if self._ibron_orig_netsetup is not None:
                cleanup_steps.append(self._wf_ibron_restore_netsetup)
            if self._ibron_attached_node is True:
                cleanup_steps.append(self._wf_ibron_detach_node)
            if len(cleanup_steps) > 0:
                wf = Workflow(cleanup_steps,
                              requester=SilentRequester(),
                              server=self.server,
                              node=node)
                wf.run()

    def save_pid_file(self, pid_file):
        self._pid_file = pid_file

    def interrupt(self):
        if self._pid_file is not None:
            try:
                pid = int(Path(self._pid_file).read_text().strip())
                os.kill(pid, signal.SIGKILL)
                print(f"killed pid {pid} of image build session "
                      "upon client request")
            except Exception:
                pass
