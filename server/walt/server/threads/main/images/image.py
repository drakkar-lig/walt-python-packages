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
IMAGE_DIFF_PATH='/var/lib/walt/images/%s/diff'
ERROR_BAD_IMAGE_NAME='''\
Bad name: expected format is <name> or <name>:<tag>.
Only lowercase letters, digits and dash(-) characters are allowed in <name> and <tag>.
'''

def get_mount_path(image_fullname):
    mount_path, dummy = get_mount_info(image_fullname)
    return mount_path

def get_mount_info(image_fullname):
    sub_path = re.sub('[^a-zA-Z0-9/-]+', '_', image_fullname)
    return IMAGE_MOUNT_PATH % sub_path, IMAGE_DIFF_PATH % sub_path

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

FS_CMD_PATTERN = 'docker run --rm --entrypoint %%(prog)s %(image)s %%(prog_args)s'

class NodeImage(object):
    def __init__(self, db, docker, fullname, created_at = None):
        self.db = db
        self.docker = docker
        self.rename(fullname)
        self.last_created_at = created_at
        self.last_top_layer_id = None
        self.mount_path = None
        self.mounted = False
        self.server_ip = get_server_ip()
        self.filesystem = Filesystem(FS_CMD_PATTERN % dict(image = self.fullname))
        self.task_label = None
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
            self.get_created_at()   # prepare created_at value
    def get_created_at(self):
        if not self.ready:
            return None
        top_layer_id = self.get_top_layer_id()
        if self.last_created_at == None or self.last_top_layer_id != top_layer_id:
            self.last_created_at = self.docker.local.get_creation_time(self.fullname)
        self.last_top_layer_id = top_layer_id
        return self.last_created_at
    def get_node_models(self):
        labels = self.docker.local.get_labels(self.fullname)
        return labels['walt.node.models'].split(',')
    def get_top_layer_id(self):
        assert (self.ready), \
            'Tried to get top layer id of image %s which is not ready.' % \
            self.fullname
        return self.docker.local.get_top_layer_id(self.fullname)
    def __del__(self):
        if self.mounted:
            self.unmount()
    def get_mount_info(self):
        return get_mount_info(self.fullname)
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
        self.mount_path, self.diff_path = self.get_mount_info()
        failsafe_makedirs(self.mount_path)
        failsafe_makedirs(self.diff_path)
        self.docker.local.image_mount(self.fullname, self.diff_path, self.mount_path)
        self.mounted = True
    def mount(self, requester = None):
        print 'Mounting %s...' % self.fullname
        self.os_mount()
        setup(self)
        print 'Mounting %s... done' % self.fullname
    def os_unmount(self):
        while not succeeds('umount %s 2>/dev/null' % self.mount_path):
            time.sleep(0.1)
        while True:
            try:
                shutil.rmtree(self.diff_path)
            except OSError:
                time.sleep(0.1)
                continue
            break
        os.rmdir(self.mount_path)
        self.mounted = False
    def unmount(self):
        print 'Un-mounting %s...' % self.fullname,
        self.os_unmount()
        print 'done'

