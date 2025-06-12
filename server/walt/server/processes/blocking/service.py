from functools import cache

from walt.common.crypto.blowfish import BlowFish
from walt.common.crypto.dh import DHPeer
from walt.server.exttools import docker
from walt.server.processes.blocking.cmd import run_shell_cmd
from walt.server.processes.blocking.devices.topology import TopologyManager
from walt.server.processes.blocking.images.clone import clone
from walt.server.processes.blocking.images.commit import commit
from walt.server.processes.blocking.images.metadata import update_hub_metadata
from walt.server.processes.blocking.images.publish import publish
from walt.server.processes.blocking.images.pull import pull_image
from walt.server.processes.blocking.images.search import search
from walt.server.processes.blocking.images.squash import squash
from walt.server.processes.blocking.images.update import update_default_images
from walt.server.processes.blocking.registries import (
    DockerDaemonClient,
    get_registry_client,
    MissingRegistryCredentials,
)


class CachingRequester:
    def __init__(self, context):
        self._remote_requester = context.remote_service.do_sync.requester

    @cache
    def get_username(self):
        return self._remote_requester.get_username()

    @cache
    def get_registry_credentials(self, registry_label):
        dh_peer = DHPeer()
        credentials = self._remote_requester.get_registry_encrypted_credentials(
            registry_label, dh_peer.pub_key
        )
        if credentials is None:
            raise MissingRegistryCredentials(registry_label)
        dh_peer.establish_session(credentials["client_pub_key"])
        symmetric_key = dh_peer.symmetric_key
        cypher = BlowFish(symmetric_key)
        password = cypher.decrypt(credentials["encrypted_password"])
        return credentials["username"], password

    def ensure_registry_conf_has_credentials(self, registry_label):
        # this is an alias to get_registry_credentials() but we do
        # not need the result
        self.get_registry_credentials(registry_label)

    @cache
    def get_registry_username(self, registry_label):
        username = self._remote_requester.get_registry_username(registry_label)
        if username is None:
            raise MissingRegistryCredentials(registry_label)
        else:
            return username

    # other attributes & methods are not cached because they have
    # side effects remotely or remote values may change during the time
    # of the local blocking task
    def __getattr__(self, attr):
        return getattr(self._remote_requester, attr)


class BlockingTasksContextService:
    def __init__(self, service, context):
        self.db = service.db
        self.topology = service.topology
        self.docker_daemon = service.docker_daemon
        self.requester = CachingRequester(context)
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

    def update_default_images(self, *args, **kwargs):
        return update_default_images(self.requester, self.server, *args, **kwargs)

    def pull_image(self, image_fullname, anonymous):
        if anonymous:
            requester = None
        else:
            requester = self.requester
        return pull_image(requester, self.server, image_fullname)

    def registry_login(self, label):
        registry = get_registry_client(self.requester, label)
        return registry.login(self.requester)

    def list_docker_daemon_images(self):
        if self.docker_daemon is None:
            return []
        else:
            return self.docker_daemon.images()

    def pull_docker_daemon_image(self, fullname):
        if self.docker_daemon is None:
            return
        else:
            return self.docker_daemon.pull(None, self.server, fullname)

    def rescan_topology(self, *args, **kwargs):
        return self.topology.rescan(
            self.requester, self.server, self.db, *args, **kwargs
        )

    def topology_tree(self, *args, **kwargs):
        return self.topology.tree(self.requester, self.server, self.db, *args, **kwargs)

    def restore_poe_on_all_ports(self):
        return self.topology.restore_poe_on_all_ports(self.server, self.db)

    def run_shell_cmd(self, *args, pipe_outstreams=False, **kwargs):
        if pipe_outstreams:
            kwargs.update(
                stdout=self.requester.stdout,
                stderr=self.requester.stderr,
            )
        return run_shell_cmd(*args, **kwargs)

    def report_lldp_neighbor(self, *args, **kwargs):
        self.topology.report_lldp_neighbor(self.server, self.db, *args, **kwargs)

class BlockingTasksService(object):
    def __init__(self):
        if docker is not None:
            self.docker_daemon = DockerDaemonClient()
        else:
            self.docker_daemon = None
        self.db = None  # to be updated shortly
        self.topology = TopologyManager()

    def __getattr__(self, method_name):
        service = self

        def m(context, *args, **kwargs):
            context_service = BlockingTasksContextService(service, context)
            result = getattr(context_service, method_name)(*args, **kwargs)
            return result

        return m
