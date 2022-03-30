import json
import shutil
import time
from pathlib import Path
from subprocess import CalledProcessError

from walt.server.exttools import buildah, podman, mount, umount, findmnt

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

class WalTLocalRepository:
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
    def associate_name_to_id(self, fullname, image_id):
        self.names_cache[fullname] = image_id
    def add_repo(self, fullname):
        if fullname.startswith('walt/'):
            return 'localhost/' + fullname
        else:
            return 'docker.io/' + fullname
    def tag(self, old_fullname, new_fullname):
        if self.image_exists(new_fullname):
            # take care not making previous version of image a dangling image
            podman.rmi(self.add_repo(new_fullname))
        if old_fullname in self.names_cache:
            self.names_cache[new_fullname] = self.names_cache[old_fullname]
        else:
            self.names_cache.pop(new_fullname, None)
        podman.tag(old_fullname, self.add_repo(new_fullname))
    def rmi(self, fullname, ignore_missing = False):
        self.untag(fullname, ignore_missing = ignore_missing)
    def untag(self, fullname, ignore_missing = False):
        if ignore_missing and not self.image_exists(fullname):
            return  # nothing to do
        # caution: we are not using "podman untag" because its behaviour is
        # unexpected (at least in version 1.9.3: when an image has several docker tags,
        # it removes all docker tags irrespectively of the one specified).
        podman.rmi(self.add_repo(fullname))
        self.names_cache.pop(fullname, None)
    def deep_inspect(self, image_id_or_fullname):
        podman_id = image_id_or_fullname
        if '/' in podman_id:
            podman_id = self.add_repo(podman_id)
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
            podman.image.exists(self.add_repo(fullname))
            return True
        except CalledProcessError:
            return False
    def refresh_cache(self):
        self.names_cache = {}
        for line in podman.images('--format', 'table {{.ID}}|{{.Repository}}:{{.Tag}}',
                                    '--filter', 'dangling=false',
                                    '--no-trunc', '--noheading').splitlines():
            sha_id, podman_image_name = line.split('|')
            image_id = sha_id[7:]   # because it starts with "sha256:"
            # buildah may manage several repos, we do not need it here, discard this repo prefix
            fullname = podman_image_name.split('/', 1)[1]
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
