import asyncio
import itertools
import json
import sys

from walt.common.formatting import indicate_progress
from walt.server import conf
from walt.server.exttools import docker, podman, skopeo
from walt.server.processes.blocking.images.tools import update_main_process_about_image
from walt.server.tools import async_json_http_get, get_registry_info

SKOPEO_RETRIES = 10
REGISTRY = "docker.io"


class RegistryAuthRequired(Exception):
    pass


class RegistryClientBase:
    def __init__(
        self, label, podman_url_prefix, login_host, protocol, auth, anonymous_operations
    ):
        assert auth in ("basic", "none")
        assert protocol in ("https", "http", "https-no-verify", "custom")
        self.label = label
        self.podman_url_prefix = podman_url_prefix
        self.login_host = login_host
        self.protocol = protocol
        self.auth = auth
        self.anonymous_operations = anonymous_operations

    def op_needs_authentication(self, op):
        if self.auth == "none":
            return False
        if op in self.anonymous_operations:
            return False
        return True

    def checker(self, line):
        if "error" in line.lower():
            raise Exception(line.strip())

    def get_registry_host(self):
        raise NotImplementedError

    def get_fullname_with_remote_user(self, requester, image_fullname):
        if self.auth == "none":
            # walt user names directly map to remote user names
            return image_fullname
        # we have a real authentication:
        # walt and remote registry accounts may have a different username
        image_user, image_name = image_fullname.split("/")
        if image_user == "waltplatform":
            # ok, waltplatform does not change, it is not a real user
            return image_fullname
        assert requester is not None
        walt_user = requester.get_username()
        remote_user = requester.get_registry_username(self.label)
        if image_user == walt_user:
            image_user = remote_user
        return f"{image_user}/{image_name}"

    def get_podman_push_url(self, requester, image_fullname):
        remote_image_fullname = self.get_fullname_with_remote_user(
            requester, image_fullname
        )
        return f"{self.podman_url_prefix}{remote_image_fullname}"

    def get_origin_clone_url(self, requester, image_fullname):
        remote_image_fullname = self.get_fullname_with_remote_user(
            requester, image_fullname
        )
        return f"{self.label}:{remote_image_fullname}"

    def get_podman_pull_url(self, image_fullname):
        return f"{self.podman_url_prefix}{image_fullname}"

    def get_tool_opts(self, requester, op):
        opts = []
        if self.protocol == "https":
            opts += ["--tls-verify=true"]
        else:
            opts += ["--tls-verify=false"]
        if self.op_needs_authentication(op):
            if requester is None:
                raise RegistryAuthRequired(
                    'Anonymous operation denied on "{self.label}" registry.'
                )
            username, password = requester.get_registry_credentials(self.label)
            if op == "login":
                opts += ["--username", username, "--password", password]
            else:
                opts += ["--creds", f"{username}:{password}"]
        return opts

    def pull(self, requester, server, image_fullname):
        url = self.get_podman_pull_url(image_fullname)
        label = "Downloading %s" % image_fullname
        args = self.get_tool_opts(requester, "pull") + [url]
        stream = podman.pull.stream(*args)
        indicate_progress(sys.stdout, label, stream, self.checker)
        # we rename all our images with prefix docker.io
        # (images downloaded from the docker daemon get this prefix)
        if not url.startswith("docker.io") and not url.startswith("docker-daemon:"):
            docker_io_url = "docker.io/" + url.split("/", maxsplit=1)[1]
            podman.tag(url, docker_io_url)
            podman.rmi(url)  # remove the previous image name
        update_main_process_about_image(server, image_fullname)

    def login(self, requester):
        if self.auth == "none":
            return True
        try:
            args = self.get_tool_opts(requester, "login") + [self.login_host]
            podman.login(*args)
        except Exception as e:
            print(e)
            requester.stdout.write(f"Sorry, {self.label} registry login FAILED.\n")
            return False
        return True

    def push(self, requester, image_fullname):
        url = self.get_podman_push_url(requester, image_fullname)
        args = self.get_tool_opts(requester, "push") + [image_fullname, url]
        stream = podman.push.stream(*args)
        label = "Pushing %s" % image_fullname
        indicate_progress(sys.stdout, label, stream, self.checker)
        return True

    def get_labels(self, requester, image_fullname):
        return asyncio.run(self.async_get_labels(requester, image_fullname))

    async def async_get_labels(self, requester, image_fullname):
        raise NotImplementedError


class DockerDaemonClient(RegistryClientBase):
    def __init__(self):
        super().__init__("docker", "docker-daemon:", None, "custom", "none", ())

    def images(self):
        return asyncio.run(self.async_images())

    async def async_images(self):
        results = []
        for line in docker.image.ls(
            "--format",
            "{{.Repository}} {{.Tag}}",
            "--filter",
            "dangling=false",
            "--filter",
            "label=walt.node.models",
        ).splitlines():
            repo_name, tag = line.strip().split()
            if tag == "<none>":
                continue
            results.append(repo_name + ":" + tag)
        return results

    async def async_get_labels(self, requester, image_fullname):
        json_labels = await docker.image.inspect.awaitable(
            "--format", "{{json .Config.Labels}}", image_fullname
        )
        return json.loads(json_labels)


class SkopeoRegistryClient(RegistryClientBase):
    async def async_get_config(self, requester, fullname):
        print(f"retrieving config from {self.label}: {fullname}")
        url = "docker://" + self.get_podman_pull_url(fullname)
        args = self.get_tool_opts(requester, "inspect") + ["--config", url]
        for _ in range(SKOPEO_RETRIES):
            try:
                data = await skopeo.inspect.awaitable(*args)
                return json.loads(data)
            except RegistryAuthRequired:
                raise
            except Exception:
                continue  # retry
        raise Exception("Failed to download config for image: " + fullname)

    async def async_get_labels(self, requester, fullname):
        config = await self.async_get_config(requester, fullname)
        if "config" not in config:
            print("{fullname}: unknown image config format.".format(fullname=fullname))
            return {}
        if "Labels" not in config["config"]:
            print("{fullname}: image has no labels.".format(fullname=fullname))
            return {}
        return config["config"]["Labels"]


class DockerHubClient(SkopeoRegistryClient):
    def __init__(self):
        super().__init__(
            "hub",
            "docker.io/",
            "docker.io",
            "https",
            "basic",
            ("pull", "inspect", "search"),
        )

    async def async_search(self, term):
        for page in itertools.count(1):
            url = (
                "https://index.docker.io/v1/search?q=%(term)s&n=100&page=%(page)s"
                % dict(term=term, page=page)
            )
            page_info = await async_json_http_get(url)
            for result in page_info["results"]:
                yield result
            if page_info["num_pages"] == page:
                break

    async def async_multi_page_hub_docker_com_query(self, url, json_name):
        url = f"https://hub.docker.com/{url}?page_size=100"
        while url is not None:
            page_info = await async_json_http_get(url)
            for res in page_info["results"]:
                yield res[json_name]
            url = page_info["next"]

    async def async_list_user_repos(self, user):
        url = f"v2/repositories/{user}/"
        async for res in self.async_multi_page_hub_docker_com_query(url, "name"):
            yield res

    async def async_list_image_tags(self, image_name):
        url = f"v2/repositories/{image_name}/tags"
        async for res in self.async_multi_page_hub_docker_com_query(url, "name"):
            yield res


class DockerRegistryV2Client(SkopeoRegistryClient):
    def __init__(self, label, host, port, protocol, auth, **kwargs):
        self.host, self.port = host, port
        super().__init__(label, f"{host}:{port}/", f"{host}:{port}", protocol, auth, ())

    async def async_multi_page_registry_v2_query(self, requester, url, json_name):
        https_verify = self.protocol == "https"
        base_proto = self.protocol.split("-")[0]  # https-no-verify -> https
        url = f"{base_proto}://{self.host}:{self.port}/{url}?n=100"
        if self.auth == "basic":
            if requester is None:
                raise RegistryAuthRequired(
                    'Anonymous operation denied on "{self.label}" registry.'
                )
            username, password = requester.get_registry_credentials(self.label)
            user_auth_pattern = f"{username}:{password}@"
        else:
            user_auth_pattern = None
        while True:
            # note: we have to add credentials at each iteration, because they
            # are not present in the 'next' link
            if user_auth_pattern is not None:
                url = url.replace(
                    f"{base_proto}://", f"{base_proto}://{user_auth_pattern}"
                )
            json, links = await async_json_http_get(
                url, return_links=True, https_verify=https_verify
            )
            for result in list(json[json_name]):
                yield result
            if "next" in links:
                url = str(links["next"]["url"])
            else:
                break

    async def async_catalog(self, requester):
        async for res in self.async_multi_page_registry_v2_query(
            requester, "v2/_catalog", "repositories"
        ):
            yield res

    async def async_list_image_tags(self, requester, image_name):
        async for res in self.async_multi_page_registry_v2_query(
            requester, f"v2/{image_name}/tags/list", "tags"
        ):
            yield res


def get_custom_registry_client(label):
    reg_info = get_registry_info(label)
    return DockerRegistryV2Client(**reg_info)


def get_registry_clients(requester=None):
    clients = []
    if requester is None:
        errstream = sys.stderr
    else:
        errstream = requester.stderr
    for reg_info in conf["registries"]:
        api = reg_info["api"]
        if api == "docker-hub":
            client = DockerHubClient()
        elif api == "docker-registry-v2":
            client = DockerRegistryV2Client(**reg_info)
        else:
            errstream.write(
                f"Unknown registry api '{api}' in configuration, ignoring.\n"
            )
            continue
        clients.append((reg_info["label"], client))
    return clients


def get_registry_client(requester, in_label):
    for label, reg_client in get_registry_clients(requester):
        if label == in_label:
            return reg_client
