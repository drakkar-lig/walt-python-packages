from walt.common.crypto.blowfish import BlowFish
from walt.server.tools import indicate_progress
from walt.server import const
from docker import Client, errors
from datetime import datetime
from plumbum.cmd import mount
import os, sys, requests, shlex, json, itertools

DOCKER_TIMEOUT=None
AUFS_BR_LIMIT=127
AUFS_BR_MOUNT_LIMIT=42
REGISTRY='https://index.docker.io/v1/'
LOGIN_PULL_TEMPLATE = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repository}:pull"
GET_MANIFEST_TEMPLATE = "https://registry.hub.docker.com/v2/{repository}/manifests/{tag}"


def docker_command_split(cmd):
    args = shlex.split(cmd)
    return dict(
        entrypoint=args[0],
        command=args[1:]
    )

class DockerLocalClient:
    def __init__(self, c):
        self.c = c
        self.layer_id_cache = {}
    def tag(self, old_fullname, new_fullname):
        reponame, tag = new_fullname.split(':')
        self.c.tag(image=old_fullname, repository=reponame, tag=tag)
    def rmi(self, fullname):
        self.c.remove_image(image=fullname, force=True)
    def untag(self, fullname, ignore_missing = False):
        if ignore_missing:
            try:
                self.rmi(fullname)
            except errors.NotFound:
                pass
        else:
            self.rmi(fullname)
    def get_images(self):
        return self.c.images()
    def iter_images(self):
        for i in self.c.images():
            if i['RepoTags'] is None:
                continue
            for tag in i['RepoTags']:
                yield (tag, i)
    def get_creation_time(self, image_fullname):
        for fullname, info in self.iter_images():
            if image_fullname == fullname:
                return datetime.fromtimestamp(info['Created'])
    def list_running_containers(self):
        return [ name.lstrip('/') for name in
                    sum([ cont['Names'] for cont in
                            self.c.containers() ], []) ]
    def start_container(self, image_fullname, cmd):
        params = dict(image=image_fullname)
        params.update(docker_command_split(cmd))
        cid = self.c.create_container(**params).get('Id')
        self.c.start(container=cid)
        return cid
    def wait_container(self, cid_or_cname):
        self.c.wait(container=cid_or_cname)
    def stop_container(self, cid_or_cname):
        try:
            self.c.kill(container=cid_or_cname)
        except:
            pass
        try:
            self.c.wait(container=cid_or_cname)
        except:
            pass
        try:
            self.c.remove_container(container=cid_or_cname)
        except:
            pass
    def commit(self, cid_or_cname, dest_fullname, msg):
        reponame, tag = dest_fullname.split(':')
        self.c.commit(
                container=cid_or_cname,
                repository=reponame,
                tag=tag,
                message=msg)
    def get_top_layer_id(self, image_fullname):
        return next(self.get_layer_ids(image_fullname))
    def get_layer_ids(self, image_fullname):
        image_info = self.c.inspect_image(image_fullname)
        if not image_info['Id'].startswith("sha256:"):
            raise Exception('Docker internal format not understood. Update docker?')
        # 1- get info about layers
        for layer_diff in image_info['RootFS']['Layers'][::-1]:
            # 2- get associated layer ID
            layer_id = self.layer_id_cache.get(layer_diff, None)
            if layer_id is None:
                self.update_layer_id_cache()
                layer_id = self.layer_id_cache.get(layer_diff)
            yield layer_id
    def update_layer_id_cache(self):
        # for each dir '/var/lib/docker/image/aufs/layerdb/sha256/<id>'
        # associate the diff ID written in file 'diff' with the layer ID
        # written in 'cache-id' file.
        self.layer_id_cache = {}
        layerdb = '/var/lib/docker/image/aufs/layerdb/sha256'
        for layer in os.listdir(layerdb):
            with open(layerdb + '/' + layer + '/diff') as layer_diff_file:
                diff_id = layer_diff_file.read()
            with open(layerdb + '/' + layer + '/cache-id') as layer_cache_id_file:
                layer_id = layer_cache_id_file.read()
            self.layer_id_cache[diff_id] = layer_id
    def get_image_layers(self, image_fullname):
        layer_ids = self.get_layer_ids(image_fullname)
        for layer_id in layer_ids:
            diff_dir = '/var/lib/docker/aufs/diff/' + layer_id
            if len(os.listdir(diff_dir)) > 0:
                yield diff_dir
    def get_container_name(self, cid):
        try:
            container = self.c.inspect_container(cid)
            return container['Name'].lstrip('/')
        except errors.NotFound:
            return None
    def events(self):
        return self.c.events(decode=True)
    def image_mount(self, image_fullname, diff_path, mount_path):
        layers = self.get_image_layers(image_fullname)
        branches = [ layer + '=ro+wh' for layer in layers ]
        branches.insert(0, diff_path + '=rw')
        if len(branches) > AUFS_BR_LIMIT:
            raise Exception('Cannot mount image: too many filesystem layers.')
        else:
            # we can mount up to AUFS_BR_MOUNT_LIMIT branches at once
            branches_opt = 'br=' + ':'.join(branches[:AUFS_BR_MOUNT_LIMIT])
            mount('-t', 'aufs', '-o', branches_opt, 'none', mount_path)
            # append others one by one
            for branch in branches[AUFS_BR_MOUNT_LIMIT:]:
                mount('-o', 'remount,append=' + branch, mount_path)
    def build(self, *args, **kwargs):
        return self.c.build(*args, **kwargs)
    def get_labels(self, image_fullname):
        image_info = self.c.inspect_image(image_fullname)
        config = image_info['Config']
        if 'Labels' not in config:
            return {}
        return config['Labels']

class DockerHubClient:
    def __init__(self, c):
        self.c = c
    def pull(self, image_fullname, requester = None):
        reponame, tag = image_fullname.split(':')
        label = 'Downloading %s' % image_fullname
        def checker(line):
            info = eval(line.strip())
            if 'error' in info:
                raise Exception(info['errorDetail']['message'])
        stream = self.c.pull(reponame, tag=requests.utils.quote(tag), stream=True)
        indicate_progress(sys.stdout, label, stream, checker)
    def login(self, dh_peer, auth_conf, requester):
        try:
            symmetric_key = dh_peer.symmetric_key
            cypher = BlowFish(symmetric_key)
            password = cypher.decrypt(auth_conf['encrypted_password'])
            # Note: the docker hub API requires the email argument
            # to be provided because it may be used to register a new user.
            # Here, the user already exists, so the email will not be used.
            self.c.login(   username = auth_conf['username'],
                            password = password,
                            email    = 'email@fake.fr',
                            registry = REGISTRY,
                            reauth   = True)
        except Exception as e:
            print e
            requester.stdout.write('FAILED.\n')
            return False
        return True
    def push(self, image_fullname, dh_peer, auth_conf, requester):
        reponame, tag = image_fullname.split(':')
        if not self.login(dh_peer, auth_conf, requester):
            return False
        stream = self.c.push(reponame, tag=requests.utils.quote(tag), stream=True)
        label = 'Pushing %s' % image_fullname
        indicate_progress(sys.stdout, label, stream)
        return True
    def search(self, term):
        results = []
        for page in itertools.count(1):
            url = 'https://index.docker.io/v1/search?q=%(term)s&n=100&page=%(page)s' % \
                    dict(   term = term,
                            page = page)
            page_info = requests.get(url).json()
            results += page_info['results']
            if page_info['num_pages'] == page:
                break
        return results
    def list_user_repos(self, user):
        url = 'https://hub.docker.com/v2/repositories/%(user)s/?page_size=100' % \
                    dict(user = user)
        while url is not None:
            page_info = requests.get(url).json()
            for res in page_info['results']:
                yield res['name']
            url = page_info['next']
    def list_image_tags(self, image_name):
        url = 'https://registry.hub.docker.com/v1/repositories/%(image_name)s/tags' % \
                    dict(image_name = image_name)
        for elem in requests.get(url, timeout=DOCKER_TIMEOUT).json():
            tag = requests.utils.unquote(elem['name'])
            yield tag
    def get_manifest(self, fullname):
        print('retrieving manifest from hub: ' + fullname)
        reponame, tag = fullname.split(':')
        token = requests.get(LOGIN_PULL_TEMPLATE.format(repository=reponame), json=True).json()["token"]
        result = requests.get(
            GET_MANIFEST_TEMPLATE.format(repository=reponame, tag=tag),
            headers={"Authorization": "Bearer {}".format(token) },
            json=True
        ).json()
        if 'errors' in result:
            raise Exception('Downloading manifest failed.')
        return result
    def get_labels(self, fullname):
        manifest = self.get_manifest(fullname)
        v1Compatibility_field = json.loads(manifest['history'][0]["v1Compatibility"])
        labels = v1Compatibility_field["config"]["Labels"]
        if labels is None:
            return {}
        else:
            return labels

class DockerClient(object):
    def __init__(self):
        self.c = Client(base_url='unix://var/run/docker.sock', version='auto',
                timeout=DOCKER_TIMEOUT)
        self.local = DockerLocalClient(self.c)
        self.hub = DockerHubClient(self.c)
    def self_test(self):
        try:
            self.c.search(term='walt-node')
        except:
            return False
        return True
