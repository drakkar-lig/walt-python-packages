import functools
from walt.server.process import RPCProcessConnector, RPCService
from walt.server.processes.main.images.tools import handle_missing_credentials


class BlockingTasksManager(RPCProcessConnector):
    def __init__(self):
        super().__init__(local_context=False,
                         label="main-to-blocking",
                         serialize_reqs=True)  # send tasks to blocking 1 by 1

    def configure(self, server):
        RPCProcessConnector.configure(self, RPCService(server=server))
        self.server = server

    def session(self, requester):
        local_service = RPCService(requester=requester, server=self.server)
        return self.create_session(local_service=local_service)

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
        self.session(requester).do_async.update_hub_metadata(*args, **kwargs).then(
            result_cb
        )

    def _anon_pull_image(self, image_fullname, result_cb):
        self.do_async.pull_image(image_fullname, anonymous=True).then(result_cb)

    def _auth_pull_image(self, requester, image_fullname, result_cb):
        self.session(requester).do_async.pull_image(
            image_fullname, anonymous=False
        ).then(result_cb)

    def pull_image(self, requester, image_fullname, result_cb):
        def callback(result):
            if result[0] == "OK":
                result_cb((True,))
            else:
                result_cb((False, result[1]))  # result[1]: failure message
        if requester is None:
            blocking_func = functools.partial(self._anon_pull_image, image_fullname)
        else:
            blocking_func = functools.partial(
                    self._auth_pull_image, requester, image_fullname)
        handle_missing_credentials(requester, blocking_func, callback)

    def registry_login(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.registry_login(*args, **kwargs).then(result_cb)

    def rescan_topology(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.rescan_topology(*args, **kwargs).then(
            result_cb
        )

    def topology_tree(self, requester, result_cb, *args, **kwargs):
        self.session(requester).do_async.topology_tree(*args, **kwargs).then(result_cb)

    def run_shell_cmd(self, requester, result_cb, cmd, **kwargs):
        self.session(requester).do_async.run_shell_cmd(cmd, **kwargs).then(result_cb)

    def update_default_images(self, requester, cb, *args, **kwargs):
        return self.session(requester).do_async.update_default_images(
                *args, **kwargs).then(cb)

    def report_lldp_neighbor(self, *args, **kwargs):
        self.session(None).do_async.report_lldp_neighbor(*args, **kwargs)

    # sync calls will block the 'main' process, so should only be used e.g. during
    # service startup.
    def sync_list_docker_daemon_images(self):
        return self.session(None).do_sync.list_docker_daemon_images()

    def sync_pull_docker_daemon_image(self, fullname):
        return self.session(None).do_sync.pull_docker_daemon_image(fullname)
