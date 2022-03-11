import itertools
import json
import re
import requests
import shutil
import sys
import time
import uuid
from pathlib import Path
from subprocess import CalledProcessError

from walt.common.crypto.blowfish import BlowFish
from walt.common.formatting import indicate_progress
from walt.server.exttools import buildah, podman, skopeo, mount, umount, findmnt, docker

DOCKER_HUB_TIMEOUT=None
SKOPEO_RETRIES=10
REGISTRY='docker.io'
MAX_IMAGE_LAYERS = 128
METADATA_CACHE_FILE = Path('/var/cache/walt/images.metadata')

# 'buildah mount' does not mount the overlay filesystem with appropriate options to allow nfs export.
# let's fix this.
def remount_with_nfs_export_option(mountpoint):
    # retrieve mount info
    json_info = findmnt('--json', mountpoint)
    mount_info = json.loads(json_info)['filesystems'][0]
    source = mount_info['source']
    fstype = mount_info['fstype']
    options = mount_info['options'].split(',')
    # update options
    new_options = [ 'rw', 'relatime', 'index=on', 'nfs_export=on' ] + \
                  [ opt for opt in options \
                    if opt.startswith('lowerdir') or \
                       opt.startswith('upperdir') or \
                       opt.startswith('workdir') ]
    # umount
    umount(mountpoint)
    # overlay has a check in place to prevent mounting the same file system
    # twice if volatile was already specified.
    for opt in options:
        if opt.startswith('workdir'):
            workdir = Path(opt[len('workdir='):])
            incompat_volatile = workdir / "work" / "incompat" / "volatile"
            if incompat_volatile.exists():
                shutil.rmtree(incompat_volatile)
            break
    # re-mount
    mount('-t', fstype, '-o', ','.join(new_options), source, mountpoint)

def mount_exists(mountpoint):
    try:
        findmnt('--json', mountpoint)
    except CalledProcessError:
        return False
    return True

def add_repo(fullname):
    if fullname.startswith('walt/'):
        return 'localhost/' + fullname
    else:
        return 'docker.io/' + fullname

class DockerLocalClient:
    def __init__(self):
        self.names_cache = {}
        self.metadata_cache = self.load_metadata_cache_file()
    def load_metadata_cache_file(self):
        if METADATA_CACHE_FILE.exists():
            return json.loads(METADATA_CACHE_FILE.read_text())
        else:
            return {}
    def save_metadata_cache_file(self):
        if not METADATA_CACHE_FILE.exists():
            METADATA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        METADATA_CACHE_FILE.write_text(json.dumps(self.metadata_cache))
    def clear_name_cache(self):
        self.names_cache = {}
    def tag(self, old_fullname, new_fullname):
        if self.image_exists(new_fullname):
            # take care not making previous version of image a dangling image
            podman.rmi(add_repo(new_fullname))
        if old_fullname in self.names_cache:
            self.names_cache[new_fullname] = self.names_cache[old_fullname]
        else:
            self.names_cache.pop(new_fullname, None)
        podman.tag(old_fullname, add_repo(new_fullname))
    def rmi(self, fullname, ignore_missing = False):
        self.untag(fullname, ignore_missing = ignore_missing)
    def untag(self, fullname, ignore_missing = False):
        if ignore_missing and not self.image_exists(fullname):
            return  # nothing to do
        # caution: we are not using "podman untag" because its behaviour is
        # unexpected (at least in version 1.9.3: when an image has several docker tags,
        # it removes all docker tags irrespectively of the one specified).
        podman.rmi(add_repo(fullname))
        self.names_cache.pop(fullname, None)
    def deep_inspect(self, image_id_or_fullname):
        podman_id = image_id_or_fullname
        if '/' in podman_id:
            podman_id = add_repo(podman_id)
        image_info = podman.inspect('--format',
            '{ "labels": "{{.Labels}}", "num_layers": {{len .RootFS.Layers}}, "created_at": "{{.Created}}" }',
            podman_id)
        image_info = json.loads(image_info)
        # unfortunately some recent versions of podman do not work with {{json .Labels}} format,
        # so we parse the default format obtained with {{.Labels}}.
        # we get a value such as "map[walt.node.models:pc-x86-64 walt.server.minversion:4]"
        labels = image_info['labels'].split('[')[1].split(']')[0]
        labels = { l:v for l, v in (lv.split(':') for lv in labels.split()) }
        editable = (image_info['num_layers'] < MAX_IMAGE_LAYERS)
        created_at = image_info['created_at']
        return {
            'labels': labels,
            'editable': editable,
            'created_at': created_at
        }
    def image_exists(self, fullname):
        try:
            podman.image.exists(add_repo(fullname))
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
        self.save_metadata_cache_file()
    def get_images(self):
        self.refresh_cache()
        for fullname, image_id in self.names_cache.items():
            if fullname.startswith('walt/'):
                continue
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
        return metadata
    def stop_container(self, cont_name):
        podman.rm("-f", "-i", cont_name)
    def get_commit_temp_image(self):
        return 'localhost/walt/commit-temp:' + str(uuid.uuid4()).split('-')[0]
    def commit(self, cid_or_cname, dest_fullname, tool=podman, opts=()):
        # we commit with 'docker' format to make these images compatible with
        # older walt server versions
        opts += ('-f', 'docker')
        if self.image_exists(dest_fullname):
            # take care not making previous version of image a dangling image
            image_tempname = self.get_commit_temp_image()
            args = opts + (cid_or_cname, image_tempname)
            image_id = tool.commit(*args).strip()
            tool.rm(cid_or_cname)
            podman.rmi('-f', add_repo(dest_fullname))
            podman.tag(image_tempname, add_repo(dest_fullname))
            podman.rmi(image_tempname)
        else:
            args = opts + (cid_or_cname, add_repo(dest_fullname))
            image_id = tool.commit(*args).strip()
            tool.rm(cid_or_cname)
        self.names_cache[dest_fullname] = image_id
    def events(self):
        return podman.events.stream('--format', 'json', converter = (lambda line: json.loads(line)))
    def get_mount_container_name(self, image_id):
        return 'mount:' + image_id[:12]
    def get_mount_image_name(self, image_id):
        return 'localhost/walt/mounts:' + image_id[:12]
    def image_mount(self, image_id, mount_path):
        # if server daemon was killed and restarted, the mount may still be there
        if mount_exists(mount_path):
            return False    # nothing to do
        cont_name = self.get_mount_container_name(image_id)
        try:
            buildah('from', '--pull-never', '--name', cont_name, image_id)
            # in some cases the code may remove the last tag of an image whilst it is
            # still mounted, waiting for grace time expiry. this fails.
            # in order to avoid this we attach a new tag to all images we mount.
            image_name = self.get_mount_image_name(image_id)
            podman.tag(str(image_id), image_name)
        except CalledProcessError:
            print('Note: walt server was probably not stopped properly and container still exists. Going on.')
        dir_name = buildah.mount(cont_name)
        remount_with_nfs_export_option(dir_name)
        mount('--bind', dir_name, mount_path)
        return True
    def image_umount(self, image_id, mount_path):
        cont_name = self.get_mount_container_name(image_id)
        if mount_exists(mount_path):
            while True:
                try:
                    umount(mount_path)
                    break
                except:
                    time.sleep(0.1)
                    continue
        buildah.umount(cont_name)
        buildah.rm(cont_name)
        image_name = self.get_mount_image_name(image_id)
        podman.rmi(image_name)
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
        for _ in range(SKOPEO_RETRIES):
            try:
                data = skopeo.inspect('--config', 'docker://docker.io/' + fullname)
                return json.loads(data)
            except:
                continue
        raise Exception('Failed to download config for image: ' + fullname)
    def get_labels(self, fullname):
        config = self.get_config(fullname)
        if 'config' not in config:
            print('{fullname}: unknown image config format.'.format(fullname=fullname))
            return {}
        if'Labels' not in config['config']:
            print('{fullname}: image has no labels.'.format(fullname=fullname))
            return {}
        return config['config']['Labels']

class Repositories:
    def __init__(self):
        self.local = DockerLocalClient()
        self.hub = DockerHubClient()
        if docker is not None:
            self.daemon = DockerDaemonClient()
        else:
            self.daemon = None

    def self_test(self):
        return True
