from walt.common.process import RPCProcessConnector, RPCService
from walt.common.apilink import AttrCallRunner, AttrCallAggregator

class BlockingTasksManager(RPCProcessConnector):
    def __init__(self, server):
        super().__init__(local_context = False)
        self.server = server

    def session(self, requester):
        local_service = RPCService(
                requester = requester,
                server = self.server
        )
        return self.create_session(local_service = local_service)

    def clone_image(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.clone_image(*args, **kwargs).then(result_cb)

    def search_image(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.search_image(*args, **kwargs).then(result_cb)

    def publish_image(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.publish_image(*args, **kwargs).then(result_cb)

    def squash_image(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.squash_image(*args, **kwargs).then(result_cb)

    def commit_image(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.commit_image(*args, **kwargs).then(result_cb)

    def update_hub_metadata(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.update_hub_metadata(*args, **kwargs).then(result_cb)

    def pull_image(self, image_fullname, result_cb):
        self.do_async.pull_image(image_fullname).then(result_cb)

    def hub_login(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.hub_login(*args, **kwargs).then(result_cb)

    def stream_db_logs(self, logs_handler):
        # request the blocking task to stream db logs
        self.session(logs_handler).do_async.stream_db_logs(
                            **logs_handler.params)

    def rescan_topology(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.rescan_topology(*args, **kwargs).then(result_cb)

    def topology_tree(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.topology_tree(*args, **kwargs).then(result_cb)

    def nodes_set_poe(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.nodes_set_poe(*args, **kwargs).then(result_cb)

    def run_shell_cmd(self, requester, result_cb, cmd, **kwargs):
        self.session(requester).do_async.run_shell_cmd(cmd, **kwargs).then(result_cb)

    # sync calls will block the 'main' process, so should only be used e.g. during
    # service startup.
    def sync_list_docker_daemon_images(self, requester):
        return self.session(requester).do_sync.list_docker_daemon_images()

    def sync_pull_docker_daemon_image(self, requester, fullname):
        return self.session(requester).do_sync.pull_docker_daemon_image(fullname)

