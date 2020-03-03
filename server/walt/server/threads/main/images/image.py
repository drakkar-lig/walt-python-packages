import os, re, time, shutil, shlex
from plumbum.cmd import chroot
from walt.server.threads.main.network.tools import get_server_ip
from walt.server.threads.main.filesystem import Filesystem
from walt.server.threads.main.images.setup import setup
from walt.common.tools import \
        failsafe_makedirs, succeeds

# IMPORTANT TERMINOLOGY NOTES:
#
# In the server side source code
# ------------------------------
# we follow the *docker terminology*
#
# <user>/<repository>:<tag>
# <-- reponame ----->
#        <-- name -------->
# <-- fullname ----------->
#
# notes:
# * similarly to docker, the <tag> part may be omitted in
#   <name>. In this case <tag> equals 'latest'.
# * walt knows whether or not a docker image is a walt
#   image by checking if it has a builtin label
#   'walt-image="true"'.
#   (cf. LABEL instruction of Dockerfile)
#
# In the client side source code
# ------------------------------
# we follow the *walt user point of view*:
# the 'name' of an image is actually the <name>
# described above.
#
# About clonable images
# ---------------------
# For a given user <username>=<u>,
# the usage of an image is describe by the table below:
#
# In the docker hub  | yes | yes | yes | yes | no  | no  |
# On the walt server | yes | yes | no  | no  | yes | yes |
# User is <u>        | yes | no  | yes | no  | yes | no  |
# --------------------------------------------------------
# displayed by show  | yes | no  | no  | no  | yes | no  |
# returned by search | no  | yes | yes | yes | no  | yes |
# <u> may clone it   | no  | yes | yes | yes | no  | yes |
#
# In order to clone an image, the user must specify
# a 'clonable image link' as an argument to 'walt image clone'.
# Such a clonable link is formatted as follows:
# [server|hub]:<user>/<name>

IMAGE_MOUNT_PATH='/var/lib/walt/images/%s/fs'
ERROR_BAD_IMAGE_NAME='''\
Bad name: expected format is <name> or <name>:<tag>.
Only lowercase letters, digits and dash(-) characters are allowed in <name> and <tag>.
'''

def get_mount_path(image_fullname):
    sub_path = re.sub('[^a-zA-Z0-9/-]+', '_', image_fullname)
    return IMAGE_MOUNT_PATH % sub_path
def parse_image_fullname(image_fullname):
    image_user, image_name = image_fullname.split('/')
    if image_name.endswith(':latest'):
        image_name = image_name[:-7]
    return image_fullname, image_user, image_name

def format_image_fullname(user, image_name):
    if ':' in image_name:
        repo, tag = image_name.split(':')
    else:
        repo, tag = image_name, 'latest'
    return user + '/' + repo + ':' + tag

def check_alnum_dash(token):
    return re.match('^[a-zA-Z0-9\-]+$', token)

def validate_image_name(requester, image_name):
    if  image_name.count(':') in (0,1) and \
        re.match('^[a-z0-9\-]+$', image_name.replace(':', '')):
        return True     # ok
    requester.stderr.write(ERROR_BAD_IMAGE_NAME)
    return False

FS_CMD_PATTERN = 'podman run --rm --entrypoint %%(prog)s %(image)s %%(prog_args)s'

class NodeImage(object):
    def __init__(self, db, docker, fullname, image_id = None, **metadata):
        self.db = db
        self.docker = docker
        self.rename(fullname)
        self.mount_path = None
        self.mounted = False
        self.server_ip = get_server_ip()
        self.filesystem = Filesystem(FS_CMD_PATTERN % dict(image = self.fullname))
        self.task_label = None
        self.set_metadata(image_id, **metadata)
    def set_metadata(self, image_id, created_at = None, labels = None, **kwargs):
        self.image_id = image_id
        self.created_at = created_at
        self.labels = labels
    def rename(self, fullname):
        self.fullname, self.user, self.name = parse_image_fullname(fullname)
    @property
    def ready(self):
        return self.db.select_unique('images', fullname=self.fullname).ready
    @ready.setter
    def ready(self, is_ready):
        self.db.update('images', 'fullname', fullname=self.fullname, ready=is_ready)
        self.db.commit()
        if is_ready:
            self.update_metadata()
    def update_metadata(self):
        self.set_metadata(**self.docker.local.get_metadata(self.fullname))
    def get_node_models(self):
        if self.labels is None:
            return None
        return self.labels['walt.node.models'].split(',')
    def __del__(self):
        if self.mounted:
            self.unmount()
    def ensure_temporary_mount(self):
        class TemporaryMount:
            def __init__(self, image):
                self.image = image
                self.mount_required = not image.mounted
            def __enter__(self):
                if self.mount_required:
                    self.image.os_mount()
            def __exit__(self, type, value, traceback):
                if self.mount_required:
                    self.image.os_unmount()
        return TemporaryMount(self)
    def chroot(self, cmd):
        with self.ensure_temporary_mount():
            args = shlex.split(cmd)
            return chroot(self.mount_path, *args, retcode = None).strip()
    def os_mount(self):
        self.mount_path = get_mount_path(self.fullname)
        failsafe_makedirs(self.mount_path)
        self.docker.local.image_mount(self.fullname, self.mount_path)
        self.mounted = True
    def mount(self, requester = None):
        print('Mounting %s...' % self.fullname)
        self.os_mount()
        setup(self)
        print('Mounting %s... done' % self.fullname)
    def os_unmount(self):
        self.docker.local.image_umount(self.fullname, self.mount_path)
        os.rmdir(self.mount_path)
        self.mounted = False
    def unmount(self):
        print('Un-mounting %s...' % self.fullname, end=' ')
        self.os_unmount()
        print('done')

