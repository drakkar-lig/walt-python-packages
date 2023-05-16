from __future__ import annotations

import typing

from walt.server.process import EvProcess, RPCProcessConnector, SyncRPCProcessConnector
from walt.server.processes.blocking.images.clone import clone
from walt.server.processes.blocking.images.publish import publish
from walt.server.processes.blocking.images.squash import squash
from walt.server.processes.blocking.images.commit import commit
from walt.server.processes.blocking.images.metadata import update_hub_metadata
from walt.server.processes.blocking.images.search import search
from walt.server.processes.blocking.images.pull import pull_image
from walt.server.processes.blocking.devices.topology import TopologyManager
from walt.server.processes.blocking.cmd import run_shell_cmd
from walt.server.processes.blocking.logs import stream_db_logs
from walt.server.processes.blocking.repositories import DockerDaemonClient, DockerHubClient
from walt.server.exttools import docker

class BlockingTasksContextService:
    def __init__(self, service, context):
        self.db = service.db
        self.topology = service.topology
        self.docker_daemon = service.docker_daemon
        self.requester = context.remote_service.do_sync.requester
        self.server = context.remote_service.do_sync.server

    def clone_image(self, *args, **kwargs):
        return clone(self.requester, self.server, *args, **kwargs)

    def search_image(self, *args, **kwargs):
        return search(self.requester, self.server, *args, **kwargs)

    def publish_image(self, *args, **kwargs):
        return publish(self.requester, self.server, *args, **kwargs)

    def squash_image(self, *args, **kwargs):
        return squash(self.requester, self.server, *args, **kwargs)

    def commit_image(self, *args, **kwargs):
        return commit(self.server, *args, **kwargs)

    def update_hub_metadata(self, *args, **kwargs):
        return update_hub_metadata(self.requester, *args, **kwargs)

    def stream_db_logs(self, **params):
        # note: in this case self.requester is actually a proxy to
        #       a LogsHandler object on the main thread
        return stream_db_logs(self.db, self.requester, **params)

    def pull_image(self, image_fullname):
        return pull_image(self.server, image_fullname)

    def hub_login(self):
        hub = DockerHubClient()
        return hub.login(self.requester)

    def list_docker_daemon_images(self):
        if self.docker_daemon is None:
            return []
        else:
            return self.docker_daemon.images()

    def pull_docker_daemon_image(self, fullname):
        if self.docker_daemon is None:
            return
        else:
            return self.docker_daemon.pull(self.server, fullname)

    def rescan_topology(self, *args, **kwargs):
        return self.topology.rescan(self.requester, self.server, self.db, *args, **kwargs)

    def topology_tree(self, *args, **kwargs):
        return self.topology.tree(self.requester, self.server, self.db, *args, **kwargs)

    def nodes_set_poe(self, *args, **kwargs):
        return self.topology.nodes_set_poe(self.server, self.db, *args, **kwargs)

    def restore_poe_on_all_ports(self):
        return self.topology.restore_poe_on_all_ports(self.server, self.db)

    def run_shell_cmd(self, *args, pipe_outstreams=False, **kwargs):
        if pipe_outstreams:
            kwargs.update(
                stdout = self.requester.stdout,
                stderr = self.requester.stderr,
            )
        return run_shell_cmd(*args, **kwargs)

class BlockingTasksService(object):
    def __init__(self):
        if docker is not None:
            self.docker_daemon = DockerDaemonClient()
        else:
            self.docker_daemon = None
        self.db = None      # to be updated shortly
        self.topology = TopologyManager()
    def __getattr__(self, method_name):
        service = self
        def m(context, *args, **kwargs):
            context_service = BlockingTasksContextService(service, context)
            result = getattr(context_service, method_name)(*args, **kwargs)
            return result
        return m

class ServerBlockingProcess(EvProcess):
    def __init__(self, tman, level : int):
        EvProcess.__init__(self, tman, 'server-blocking', level)
        service = BlockingTasksService()
        self.main = RPCProcessConnector(service, label = 'blocking-to-main')
        tman.attach_file(self, self.main)
        self.db = SyncRPCProcessConnector(label = 'blocking-to-db')
        tman.attach_file(self, self.db)
        service.db = self.db

    def prepare(self):
        self.register_listener(self.main)
        self.register_listener(self.db)

