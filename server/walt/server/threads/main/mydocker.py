from walt.common.crypto.blowfish import BlowFish
from walt.server.threads.main.images.image import parse_image_fullname
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

def docker_command_split(cmd):
    args = shlex.split(cmd)
    return dict(
        entrypoint=args[0],
        command=args[1:]
    )

class DockerClient(object):
    def __init__(self):
        self.c = Client(base_url='unix://var/run/docker.sock', version='auto',
                timeout=DOCKER_TIMEOUT)
        self.layer_id_cache = {}
    def self_test(self):
        try:
            self.c.search(term='walt-node')
        except:
            return False
        return True
    def pull(self, image_fullname, requester = None):
        fullname, name, repo, user, tag = parse_image_fullname(image_fullname)
        label = 'Downloading %s/%s' % (user, tag)
        def checker(line):
            info = eval(line.strip())
            if 'error' in info:
                raise Exception(info['errorDetail']['message'])
        stream = self.c.pull(name, tag=requests.utils.quote(tag), stream=True)
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
        fullname, name, repo, user, tag = parse_image_fullname(image_fullname)
        if not self.login(dh_peer, auth_conf, requester):
            return False
        stream = self.c.push(name, tag=requests.utils.quote(tag), stream=True)
        label = 'Pushing %s' % tag
        indicate_progress(sys.stdout, label, stream)
        return True
    def tag(self, old_fullname, new_fullname):
        dummy1, new_name, dummy2, dummy3, new_tag = parse_image_fullname(new_fullname)
        self.c.tag(image=old_fullname, repository=new_name, tag=new_tag)
    def rmi(self, fullname):
        self.c.remove_image(image=fullname, force=True)
    def untag(self, fullname):
        self.rmi(fullname)
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
    def lookup_remote_tags(self, image_name):
        url = const.DOCKER_HUB_GET_TAGS_URL % dict(image_name = image_name)
        for elem in requests.get(url, timeout=DOCKER_TIMEOUT).json():
            tag = requests.utils.unquote(elem['name'])
            yield (image_name.split('/')[0], tag)
    def get_local_images(self):
        return { tag: i for tag, i in self.iter_local_images() }
    def iter_local_images(self):
        for i in self.c.images():
            if i['RepoTags'] is None:
                continue
            for tag in i['RepoTags']:
                yield (tag, i)
    def get_creation_time(self, image_fullname):
        for fullname, info in self.iter_local_images():
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
        fullname, name, repo, user, tag = parse_image_fullname(dest_fullname)
        self.c.commit(
                container=cid_or_cname,
                repository=name,
                tag=tag,
                message=msg)
    def get_top_layer_id(self, image_fullname):
        image_info = self.c.inspect_image(image_fullname)
        image_id = image_info['Id']
        if image_id.startswith("sha256:"):
            # new format, this will be complicated...
            # (there are several levels of IDs...)
            image_id = image_id.split(':')[1]
            # 1- get info about top level layer
            top_layer_diff = image_info['RootFS']['Layers'][-1]
            # 2- get associated layer ID
            layer_id = self.layer_id_cache.get(top_layer_diff, None)
            if layer_id is None:
                self.update_layer_id_cache()
                layer_id = self.layer_id_cache.get(top_layer_diff)
            return layer_id
        else:
            return image_id
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
        image_id = self.get_top_layer_id(image_fullname)
        # concatenate this layer id + its ancestors listed in
        # /var/lib/docker/aufs/layers/<layer-id>
        branches = [ image_id ]
        with open('/var/lib/docker/aufs/layers/%s' % image_id) as layers_file:
            content = layers_file.read().strip()
            if content != '':
                branches += content.split('\n')
        return [ '/var/lib/docker/aufs/diff/%s' % br for br in branches ]
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
