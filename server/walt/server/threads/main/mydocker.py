from walt.common.crypto.blowfish import BlowFish
from walt.server.tools import indicate_progress
from walt.server.exttools import buildah, podman, skopeo, mount, umount, findmnt, docker
from walt.server import const
from datetime import datetime
from subprocess import run, CalledProcessError, PIPE, Popen
import time, re, os, sys, requests, json, itertools

DOCKER_HUB_TIMEOUT=None
DELAY_BEFORE_RETRY=3
REGISTRY='docker.io'
MAX_IMAGE_LAYERS = 128

def parse_date(created_at):
    # strptime does not support parsing nanosecond precision
    # remove last 3 decimals of this number
    created_at = re.sub(r'([0-9]{6})[0-9]*', r'\1', created_at)
    dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S.%f %z %Z")
    # remove subsecond precision (not needed)
    dt = dt.replace(microsecond=0)
    # convert to local time
    return dt.astimezone().replace(tzinfo=None)

# 'buildah mount' does not mount the overlay filesystem with appropriate options to allow nfs export.
# let's fix this.
def remount_with_nfs_export_option(mountpoint):
    # retrieve mount info
    json_info = findmnt('--json', mountpoint)
    mount_info = json.loads(json_info)['filesystems'][0]
    source = mount_info['source']
    fstype = mount_info['fstype']
    options = mount_info['options']
    # add appropriate options
    options += ',index=on,nfs_export=on'
    # umount
    umount(mountpoint)
    # re-mount
    mount('-t', fstype, '-o', options, source, mountpoint)

def mount_exists(mountpoint):
    try:
        findmnt('--json', mountpoint)
    except CalledProcessError:
        return False
    return True

class DockerLocalClient:
    def __init__(self):
        self.names_cache = {}
        self.metadata_cache = {}
    def clear_name_cache(self):
        self.names_cache = {}
    def tag(self, old_fullname, new_fullname):
        if self.image_exists(new_fullname):
            # take care not making previous version of image a dangling image
            podman.rmi('docker.io/' + new_fullname)
        if old_fullname in self.names_cache:
            self.names_cache[new_fullname] = self.names_cache[old_fullname]
        else:
            self.names_cache.pop(new_fullname, None)
        podman.tag(old_fullname, 'docker.io/' + new_fullname)
    def rmi(self, fullname, ignore_missing = False):
        self.untag(fullname, ignore_missing = ignore_missing)
    def untag(self, fullname, ignore_missing = False):
        if ignore_missing and not self.image_exists(fullname):
            return  # nothing to do
        # caution: we are not using "podman untag" because its behaviour is
        # unexpected (at least in version 1.9.3: when an image has several docker tags,
        # it removes all docker tags irrespectively of the one specified).
        podman.rmi('docker.io/' + fullname)
        self.names_cache.pop(fullname, None)
    def deep_inspect(self, image_id_or_fullname):
        podman_id = image_id_or_fullname
        if '/' in podman_id:
            podman_id = 'docker.io/' + podman_id
        image_info = podman.inspect('--format',
            '{ "labels": {{json .Labels}}, "num_layers": {{len .RootFS.Layers}}, "created_at": "{{.Created}}" }',
            podman_id)
        image_info = json.loads(image_info)
        editable = (image_info['num_layers'] < MAX_IMAGE_LAYERS)
        created_at = parse_date(image_info['created_at'])
        if image_info['labels'] is None:
            image_info['labels'] = {}
        return {
            'labels': image_info['labels'],
            'editable': editable,
            'created_at': created_at
        }
    def image_exists(self, fullname):
        try:
            podman.image.exists('docker.io/' + fullname)
            return True
        except CalledProcessError:
            return False
    def refresh_cache(self):
        self.names_cache = {}
        for line in buildah.images('--format', '{{.ID}}|{{.Name}}:{{.Tag}}',
                                   '--filter', 'dangling=false',
                                   '--no-trunc').splitlines():
            sha_id, buildah_image_name = line.split('|')
            image_id = sha_id[7:]   # because it starts with "sha256:"
            # buildah may manage several repos, we do not need it here, discard this repo prefix
            fullname = buildah_image_name.split('/', 1)[1]
            if not '/' in fullname:
                continue
            if 'clone-temp/walt-image:' in fullname:
                continue
            self.names_cache[fullname] = image_id
        old_metadata_cache = self.metadata_cache
        self.metadata_cache = {}
        for image_id in set(self.names_cache.values()):
            if image_id in self.metadata_cache:
                continue
            if image_id in old_metadata_cache:
                self.metadata_cache[image_id] = old_metadata_cache[image_id]
                continue
            self.metadata_cache[image_id] = self.get_metadata(image_id)
    def get_images(self):
        self.refresh_cache()
        for fullname, image_id in self.names_cache.items():
            if 'walt.node.models' not in self.metadata_cache[image_id]['labels']:
                continue
            yield fullname
    def get_metadata(self, image_id_or_fullname):
        if ':' in image_id_or_fullname:
            # fullname
            fullname = image_id_or_fullname
            image_id = self.names_cache.get(fullname)
            if image_id is None:
                self.refresh_cache()
            image_id = self.names_cache.get(fullname)
            if image_id is None:
                return None
        else:
            # image_id
            image_id = image_id_or_fullname
        metadata = self.metadata_cache.get(image_id)
        if metadata is None:
            metadata = dict(
                image_id = image_id,
                **self.deep_inspect(image_id))
            self.metadata_cache[image_id] = metadata
        return metadata
    def stop_container(self, cont_name):
        podman.rm("-f", "-i", cont_name)
    def commit(self, cid_or_cname, dest_fullname, tool=podman, opts=()):
        # we commit with 'docker' format to make these images compatible with
        # older walt server versions
        opts += ('-f', 'docker')
        if self.image_exists(dest_fullname):
            # take care not making previous version of image a dangling image
            image_tempname = 'localhost/walt-commit-' + dest_fullname
            args = opts + (cid_or_cname, image_tempname)
            image_id = tool.commit(*args).strip()
            tool.rm(cid_or_cname)
            podman.rmi('-f', 'docker.io/' + dest_fullname)
            podman.tag(image_tempname, 'docker.io/' + dest_fullname)
            podman.rmi(image_tempname)
        else:
            args = opts + (cid_or_cname, 'docker.io/' + dest_fullname)
            image_id = tool.commit(*args).strip()
            tool.rm(cid_or_cname)
        self.names_cache[dest_fullname] = image_id
    def events(self):
        return podman.events.stream('--format', 'json', converter = (lambda line: json.loads(line)))
    def image_mount(self, image_id, mount_path):
        # if server daemon was killed and restarted, the mount may still be there
        if mount_exists(mount_path):
            return False    # nothing to do
        cont_name = 'mount:' + image_id
        try:
            buildah('from', '--pull-never', '--name', cont_name, image_id)
        except CalledProcessError:
            print('Note: walt server was probably not stopped properly and container still exists. Going on.')
        dir_name = buildah.mount(cont_name)
        remount_with_nfs_export_option(dir_name)
        mount('--bind', dir_name, mount_path)
        return True
    def image_umount(self, image_id, mount_path):
        cont_name = 'mount:' + image_id
        while True:
            try:
                umount(mount_path)
                break
            except:
                time.sleep(0.1)
                continue
        buildah.umount(cont_name)
        buildah.rm(cont_name)
    def squash(self, image_fullname):
        cont_name = 'squash:' + image_fullname
        try:
            buildah('from', '--pull-never', '--name', cont_name, image_fullname)
        except CalledProcessError:
            print('Note: walt server was probably not stopped properly and container still exists.')
            print('      removing container and restarting command.')
            buildah.rm(cont_name)
            buildah('from', '--pull-never', '--name', cont_name, image_fullname)
        self.commit(cont_name, image_fullname, tool=buildah, opts=('--squash',))

class DockerDaemonClient:
    def images(self):
        for line in docker.image.ls('--format', '{{.Repository}} {{.Tag}}',
                                    '--filter', 'dangling=false',
                                    '--filter', 'label=walt.node.models').splitlines():
            repo_name, tag = line.strip().split()
            if tag == '<none>':
                continue
            yield repo_name + ':' + tag
    def get_labels(self, image_fullname):
        json_labels = docker.image.inspect('--format', '{{json .Config.Labels}}', image_fullname)
        return json.loads(json_labels)
    def checker(self, line):
        if 'error' in line.lower():
            raise Exception(line.strip())
    def pull(self, image_fullname, requester = None):
        label = 'Downloading %s' % image_fullname
        stream = podman.pull.stream('docker-daemon:' + image_fullname, out_stream='stderr')
        indicate_progress(sys.stdout, label, stream, self.checker)

class DockerHubClient:
    def checker(self, line):
        if 'error' in line.lower():
            raise Exception(line.strip())
    def pull(self, image_fullname, requester = None):
        label = 'Downloading %s' % image_fullname
        stream = podman.pull.stream(image_fullname, out_stream='stderr')
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
        for elem in requests.get(url, timeout=DOCKER_HUB_TIMEOUT).json():
            tag = requests.utils.unquote(elem['name'])
            yield tag
    def get_config(self, fullname):
        print('retrieving config from hub: ' + fullname)
        return json.loads(skopeo.inspect('--config', 'docker://docker.io/' + fullname))
    def get_labels(self, fullname):
        config = self.get_config(fullname)
        if 'config' not in config:
            print('{fullname}: unknown image config format.'.format(fullname=fullname))
            return {}
        if'Labels' not in config['config']:
            print('{fullname}: image has no labels.'.format(fullname=fullname))
            return {}
        return config['config']['Labels']

class DockerClient(object):
    def __init__(self):
        self.local = DockerLocalClient()
        self.hub = DockerHubClient()
        self.daemon = DockerDaemonClient()
    def self_test(self):
        return True
