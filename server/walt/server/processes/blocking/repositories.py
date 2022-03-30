import asyncio
import itertools
import json
import requests
import sys

from walt.common.crypto.blowfish import BlowFish
from walt.common.formatting import indicate_progress
from walt.server.exttools import buildah, podman, skopeo, docker
from walt.server.tools import async_json_http_get

SKOPEO_RETRIES=10
REGISTRY='docker.io'

class DockerDaemonClient:
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
    def get_labels(self, image_fullname):
        return asyncio.run(self.async_get_labels(image_fullname))
    async def async_get_labels(self, image_fullname):
        json_labels = await docker.image.inspect.awaitable('--format', '{{json .Config.Labels}}', image_fullname)
        return json.loads(json_labels)
    def checker(self, line):
        if 'error' in line.lower():
            raise Exception(line.strip())
    def pull(self, image_fullname):
        label = 'Downloading %s' % image_fullname
        stream = podman.pull.stream('docker-daemon:' + image_fullname, out_stream='stderr')
        indicate_progress(sys.stdout, label, stream, self.checker)

class DockerHubClient:
    def checker(self, line):
        if 'error' in line.lower():
            raise Exception(line.strip())
    def pull(self, image_fullname):
        label = 'Downloading %s' % image_fullname
        stream = podman.pull.stream(REGISTRY + '/' + image_fullname, out_stream='stderr')
        indicate_progress(sys.stdout, label, stream, self.checker)
    def login(self, dh_peer, auth_conf, requester):
        try:
            symmetric_key = dh_peer.symmetric_key
            cypher = BlowFish(symmetric_key)
            password = cypher.decrypt(auth_conf['encrypted_password'])
            # Note: the docker hub API requires the email argument
            # to be provided because it may be used to register a new user.
            # Here, the user already exists, so the email will not be used.
            podman.login(   '-u', auth_conf['username'], '--password-stdin', REGISTRY,
                            input=password)
        except Exception as e:
            print(e)
            requester.stdout.write('FAILED.\n')
            return False
        return True
    def push(self, image_fullname, dh_peer, auth_conf, requester):
        if not self.login(dh_peer, auth_conf, requester):
            return False
        stream = podman.push.stream(image_fullname, REGISTRY + '/' + image_fullname)
        label = 'Pushing %s' % image_fullname
        indicate_progress(sys.stdout, label, stream, self.checker)
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
        url = 'https://registry.hub.docker.com/v1/repositories/%(image_name)s/tags' % \
                    dict(image_name = image_name)
        tags = []
        data = await async_json_http_get(url)
        for elem in data:
            tag = requests.utils.unquote(elem['name'])
            tags += [ tag ]
        return tags
    async def async_get_config(self, fullname):
        print('retrieving config from hub: ' + fullname)
        for _ in range(SKOPEO_RETRIES):
            try:
                data = await skopeo.inspect.awaitable('--config', 'docker://docker.io/' + fullname)
                return json.loads(data)
            except:
                continue
        raise Exception('Failed to download config for image: ' + fullname)
    async def async_get_labels(self, fullname):
        config = await self.async_get_config(fullname)
        if 'config' not in config:
            print('{fullname}: unknown image config format.'.format(fullname=fullname))
            return {}
        if'Labels' not in config['config']:
            print('{fullname}: image has no labels.'.format(fullname=fullname))
            return {}
        return config['config']['Labels']

