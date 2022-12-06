import asyncio
import itertools
import json
import requests
import sys

from walt.common.crypto.dh import DHPeer
from walt.common.crypto.blowfish import BlowFish
from walt.common.formatting import indicate_progress
from walt.server import conf
from walt.server.exttools import buildah, podman, skopeo, docker
from walt.server.tools import async_json_http_get, get_registry_info
from walt.server.processes.blocking.images.tools import update_main_process_about_image

SKOPEO_RETRIES=10
REGISTRY='docker.io'

class RegistryClientBase:
    def __init__(self):
        self.https_only = True
    def checker(self, line):
        if 'error' in line.lower():
            raise Exception(line.strip())
    def get_registry_label(self):
        raise NotImplementedError
    def get_podman_url(self, image_fullname):
        raise NotImplementedError
    def get_podman_pull_url(self, image_fullname):
        return self.get_podman_url(image_fullname)
    def get_podman_push_url(self, requester, image_fullname):
        return self.get_podman_url(image_fullname)
    def get_tls_opt(self):
        if self.https_only:
            return '--tls-verify=true'
        else:
            return '--tls-verify=false'
    def pull(self, server, image_fullname):
        url = self.get_podman_pull_url(image_fullname)
        label = 'Downloading %s' % image_fullname
        stream = podman.pull.stream(self.get_tls_opt(), url, out_stream='stderr')
        indicate_progress(sys.stdout, label, stream, self.checker)
        # we rename all our images with prefix docker.io
        # (images downloaded from the docker daemon get this prefix)
        if not url.startswith('docker.io') and not url.startswith('docker-daemon:'):
            docker_io_url = 'docker.io/' + url.split('/', maxsplit=1)[1]
            podman.tag(url, docker_io_url)
            podman.rmi(url) # remove the previous image name
        update_main_process_about_image(server, image_fullname)
    def login(self, requester):
        return True    # nothing to do, overwrite in subclass if needed
    def push(self, requester, image_fullname):
        if not self.login(requester):
            return False
        url = self.get_podman_push_url(requester, image_fullname)
        stream = podman.push.stream(self.get_tls_opt(), image_fullname, url)
        label = 'Pushing %s' % image_fullname
        indicate_progress(sys.stdout, label, stream, self.checker)
        return True
    def get_labels(self, image_fullname):
        return asyncio.run(self.async_get_labels(image_fullname))
    async def async_get_labels(self, image_fullname):
        raise NotImplementedError

class DockerDaemonClient(RegistryClientBase):
    def images(self):
        return asyncio.run(self.async_images())
    async def async_images(self):
        results = []
        for line in docker.image.ls('--format', '{{.Repository}} {{.Tag}}',
                                    '--filter', 'dangling=false',
                                    '--filter', 'label=walt.node.models').splitlines():
            repo_name, tag = line.strip().split()
            if tag == '<none>':
                continue
            results.append(repo_name + ':' + tag)
        return results
    async def async_get_labels(self, image_fullname):
        json_labels = await docker.image.inspect.awaitable('--format', '{{json .Config.Labels}}', image_fullname)
        return json.loads(json_labels)
    def get_podman_url(self, image_fullname):
        return 'docker-daemon:' + image_fullname
    def get_registry_label(self):
        return 'docker'

class SkopeoRegistryClient(RegistryClientBase):
    async def async_get_config(self, fullname):
        print(f'retrieving config from {self.get_registry_label()}: {fullname}')
        skopeo_url = 'docker://' + self.get_podman_pull_url(fullname)
        for _ in range(SKOPEO_RETRIES):
            try:
                data = await skopeo.inspect.awaitable(self.get_tls_opt(), '--config', skopeo_url)
                return json.loads(data)
            except:
                continue
        raise Exception('Failed to download config for image: ' + fullname)
    async def async_get_labels(self, fullname):
        config = await self.async_get_config(fullname)
        if 'config' not in config:
            print('{fullname}: unknown image config format.'.format(fullname=fullname))
            return {}
        if 'Labels' not in config['config']:
            print('{fullname}: image has no labels.'.format(fullname=fullname))
            return {}
        return config['config']['Labels']

class DockerHubClient(SkopeoRegistryClient):
    def get_podman_url(self, image_fullname):
        return 'docker.io/' + image_fullname
    def get_podman_push_url(self, requester, image_fullname):
        # walt username may be different than the hub account
        hub_user = requester.get_hub_username()
        image_name = image_fullname.split('/')[1]
        return f'docker.io/{hub_user}/{image_name}'
    def get_registry_label(self):
        return 'hub'
    def login(self, requester):
        try:
            dh_peer = DHPeer()
            credentials = requester.get_hub_encrypted_credentials(dh_peer.pub_key)
            dh_peer.establish_session(credentials['client_pub_key'])
            symmetric_key = dh_peer.symmetric_key
            cypher = BlowFish(symmetric_key)
            password = cypher.decrypt(credentials['encrypted_password'])
            # Note: the docker hub API requires the email argument
            # to be provided because it may be used to register a new user.
            # Here, the user already exists, so the email will not be used.
            podman.login('-u', credentials['username'], '--password-stdin', REGISTRY,
                         input=password)
        except Exception as e:
            print(e)
            requester.stdout.write('Sorry, docker hub login FAILED.\n')
            return False
        return True
    async def async_search(self, term):
        for page in itertools.count(1):
            url = 'https://index.docker.io/v1/search?q=%(term)s&n=100&page=%(page)s' % \
                    dict(   term = term,
                            page = page)
            page_info = await async_json_http_get(url)
            for result in page_info['results']:
                yield result
            if page_info['num_pages'] == page:
                break
    async def async_list_user_repos(self, user):
        url = 'https://hub.docker.com/v2/repositories/%(user)s/?page_size=100' % \
                    dict(user = user)
        repos = []
        while url is not None:
            page_info = await async_json_http_get(url)
            for res in page_info['results']:
                repos.append(res['name'])
            url = page_info['next']
        return repos
    async def async_list_image_tags(self, image_name):
        url = 'https://hub.docker.com/v2/repositories/%(image_name)s/tags?page_size=100' % \
                    dict(image_name = image_name)
        tags = []
        while url is not None:
            page_info = await async_json_http_get(url)
            for res in page_info['results']:
                tags.append(res['name'])
            url = page_info['next']
        return tags

class DockerRegistryV2Client(SkopeoRegistryClient):
    def __init__(self, host, port, https_only):
        self.host, self.port, self.https_only = host, port, https_only
    def get_podman_url(self, image_fullname):
        return f'{self.host}:{self.port}/' + image_fullname
    def get_registry_label(self):
        return f'{self.host}:{self.port}'
    async def async_catalog(self):
        proto = 'https' if self.https_only else 'http'
        url = f'{proto}://{self.host}:{self.port}/v2/_catalog?n=100'
        while True:
            json, links = await async_json_http_get(url, return_links=True)
            for repo in json['repositories']:
                yield repo
            if 'next' in links:
                url = str(links['next']['url'])
            else:
                break
    async def async_list_image_tags(self, image_name):
        proto = 'https' if self.https_only else 'http'
        url = f'{proto}://{self.host}:{self.port}/v2/{image_name}/tags/list?n=100'
        tags = []
        while True:
            json, links = await async_json_http_get(url, return_links=True)
            for tag in json['tags']:
                yield tag
            if 'next' in links:
                url = str(links['next']['url'])
            else:
                break

def get_custom_registry_client(label):
    reg_info = get_registry_info(label)
    return DockerRegistryV2Client(
            reg_info['host'], reg_info['port'], reg_info['https-verify'])

def get_registry_clients(requester = None):
    clients = []
    if requester is None:
        errstream = sys.stderr
    else:
        errstream = self.requester.stderr
    for reg_info in conf['registries']:
        api = reg_info['api']
        if api == 'docker-hub':
            client = DockerHubClient()
        elif api == 'docker-registry-v2':
            client = DockerRegistryV2Client(
                    reg_info['host'], reg_info['port'], reg_info['https-verify'])
        else:
            errstream.write(f"Unknown registry api '{api}' in configuration, ignoring.\n")
            continue
        clients.append((reg_info['label'], client))
    return clients
