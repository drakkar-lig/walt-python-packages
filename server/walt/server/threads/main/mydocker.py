from walt.common.crypto.blowfish import BlowFish
from walt.server.tools import indicate_progress
from walt.server.exttools import buildah, podman, mount, umount, findmnt, docker
from walt.server import const
from datetime import datetime
from subprocess import run, CalledProcessError, PIPE, Popen
import time, re, os, sys, requests, json, itertools

DOCKER_HUB_TIMEOUT=None
REGISTRY='docker.io'
LOGIN_PULL_TEMPLATE = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repository}:pull"
GET_MANIFEST_TEMPLATE = "https://registry.hub.docker.com/v2/{repository}/manifests/{tag}"

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

class DockerLocalClient:
    def tag(self, old_fullname, new_fullname):
        buildah.tag(old_fullname, 'docker.io/' + new_fullname)
    def rmi(self, fullname, ignore_missing = False):
        self.untag(fullname, ignore_missing = ignore_missing)
    def untag(self, fullname, ignore_missing = False):
        if ignore_missing:
            try:
                buildah.rmi(fullname)
            except CalledProcessError:
                pass
        else:
            buildah.rmi(fullname)
    def parse_buildah_image_name(self, buildah_image_name):
        # buildah may manage several repos, we do not need it here, discard this repo prefix
        fullname = buildah_image_name.split('/', 1)[1]
        return fullname
    def get_images(self):
        images_info = {}
        for line in buildah.images('--format', '{{.ID}}|{{.Name}}:{{.Tag}}|{{.CreatedAtRaw}}',
                                   '--filter', 'dangling=false',
                                   '--no-trunc').splitlines():
            sha_id, buildah_image_name, created_at = line.split('|')
            image_id = sha_id[7:]   # because it starts with "sha256:"
            fullname = self.parse_buildah_image_name(buildah_image_name)
            if not '/' in fullname:
                continue
            if 'clone-temp/walt-image:' in fullname:
                continue
            if image_id not in images_info:
                images_info[image_id] = {
                    'fullnames': [ fullname ],
                    'created_at': created_at
                }
            else:
                images_info[image_id]['fullnames'].append(fullname)
        for image_id, image_info in images_info.items():
            image_labels = podman.inspect('--format', '{{json .Labels}}', image_id)
            image_labels = json.loads(image_labels)
            if 'walt.node.models' not in image_labels:
                continue
            for fullname in image_info['fullnames']:
                yield {
                    'fullname': fullname,
                    'image_id': image_id,
                    'created_at': parse_date(image_info['created_at']),
                    'labels': image_labels
                }
    def get_metadata(self, image_fullname):
        line = buildah.images('--format', '{{.ID}}|{{.CreatedAtRaw}}', '--no-trunc', image_fullname).strip()
        sha_id, created_at = line.split('|')
        image_id = sha_id[7:]   # because it starts with "sha256:"
        image_labels = podman.inspect('--format', '{{json .Labels}}', image_id)
        image_labels = json.loads(image_labels)
        return {
            'image_id': image_id,
            'created_at': parse_date(created_at),
            'labels': image_labels
        }
    def container_is_running(self, cont_name):
        output = podman.ps('-q', '--filter', 'name=' + cont_name)
        return len(output.strip()) > 0
    def stop_container(self, cont_name):
        if self.container_is_running(cont_name):
            try:
                podman.kill(cont_name)
            except:
                pass
            try:
                podman.wait(cont_name)
            except:
                pass
        try:
            podman.rm(cont_name)
        except:
            pass
    def commit(self, cid_or_cname, dest_fullname):
        podman.commit(
                cid_or_cname,
                'docker.io/' + dest_fullname)
    def events(self):
        return podman.events.stream('--format', 'json', converter = (lambda line: json.loads(line)))
    def image_mount(self, image_fullname, mount_path):
        cont_name = 'mount:' + image_fullname
        buildah('from', '--pull-never', '--name', cont_name, image_fullname)
        dir_name = buildah.mount(cont_name)
        remount_with_nfs_export_option(dir_name)
        mount('--bind', dir_name, mount_path)
    def image_umount(self, image_fullname, mount_path):
        cont_name = 'mount:' + image_fullname
        while True:
            try:
                umount(mount_path)
                break
            except:
                time.sleep(0.1)
                continue
        buildah.umount(cont_name)
        buildah.rm(cont_name)

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
        # images are saved with prefix "localhost/" when pulled from docker daemon.
        # to simplify, walt names all podman images with prefix "docker.io/".
        podman.image.tag(image_fullname, 'docker.io/' + image_fullname)
        podman.image.rm('localhost/' + image_fullname)

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
    def get_manifest(self, fullname):
        print(('retrieving manifest from hub: ' + fullname))
        reponame, tag = fullname.split(':')
        token = requests.get(LOGIN_PULL_TEMPLATE.format(repository=reponame), json=True).json()["token"]
        result = requests.get(
            GET_MANIFEST_TEMPLATE.format(repository=reponame, tag=tag),
            headers={"Authorization": "Bearer {}".format(token),
                     "Accept": "application/vnd.oci.image.manifest.v1+json" },
            json=True
        ).json()
        if 'errors' in result:
            print(result)
            raise Exception('Downloading manifest failed.')
        return result
    def get_labels(self, fullname):
        manifest = self.get_manifest(fullname)
        if 'history' in manifest:
            # legacy docker manifest format
            v1Compatibility_field = json.loads(manifest['history'][0]["v1Compatibility"])
            labels = v1Compatibility_field["config"]["Labels"]
            if labels is None:
                return {}
            else:
                return labels
        elif 'annotations' in manifest:
            # new OCI manifest format
            return manifest['annotations']
        else:
            return {}

class DockerClient(object):
    def __init__(self):
        self.local = DockerLocalClient()
        self.hub = DockerHubClient()
        self.daemon = DockerDaemonClient()
    def self_test(self):
        return True
