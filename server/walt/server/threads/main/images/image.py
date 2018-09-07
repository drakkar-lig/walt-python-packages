import os, re, time, shutil, shlex
from plumbum.cmd import chroot
from walt.server.threads.main.network.tools import get_server_ip
from walt.server.threads.main.filesystem import Filesystem
from walt.server.threads.main.images.setup import setup
from walt.common.tools import \
        failsafe_makedirs, succeeds
from walt.common.versions import API_VERSIONING, UPLOAD

# IMPORTANT TERMINOLOGY NOTES:
#
# In the client side source code
# ------------------------------
# we follow the *walt user point of view*:
# the 'name' of an image is actually the docker <tag> only.
#
# In the server side source code
# ------------------------------
# we follow the *docker terminology*
#
# <user>/<repository>:<tag>
# <-- name --------->
# <-- fullname ----------->
#
# note: all walt images have <repository>='walt-node',
# which allows to find them. (1)
# As a result of (1), all docker images that walt manages
# have a fullname with the following format:
# <username>/walt-node:<tag>
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
# [server|hub]:<user>/<image_tag>

IMAGE_MOUNT_PATH='/var/lib/walt/images/%s/fs'
IMAGE_DIFF_PATH='/var/lib/walt/images/%s/diff'

def get_mount_path(image_fullname):
    mount_path, dummy = get_mount_info(image_fullname)
    return mount_path

def get_mount_info(image_fullname):
    sub_path = re.sub('[^a-zA-Z0-9/-]+', '_', re.sub(':', '/', image_fullname))
    return IMAGE_MOUNT_PATH % sub_path, IMAGE_DIFF_PATH % sub_path

def parse_image_fullname(image_fullname):
    image_name, image_tag = image_fullname.split(':')
    image_user, image_repo = image_name.split('/')
    return image_fullname, image_name, image_repo, image_user, image_tag

def validate_image_tag(requester, image_tag):
    is_ok = re.match('^[a-zA-Z0-9\-]+$', image_tag)
    if not is_ok:
        requester.stderr.write(\
                'Bad name: Only alnum and dash(-) characters are allowed.\n')
    return is_ok

FS_CMD_PATTERN = 'docker run --rm --entrypoint %%(prog)s %(image)s %%(prog_args)s'

class NodeImage(object):
    def __init__(self, docker, fullname, is_ready, created_at = None):
        self.docker = docker
        self.rename(fullname)
        self.last_created_at = created_at
        self.last_top_layer_id = None
        self.ready = is_ready
        self.mount_path = None
        self.mounted = False
        self.server_ip = get_server_ip()
        self.filesystem = Filesystem(FS_CMD_PATTERN % dict(image = self.fullname))
        self.task_label = None
    def rename(self, fullname):
        self.fullname, self.name, dummy, self.user, self.tag = \
            parse_image_fullname(fullname)
    def set_ready(self, is_ready):
        self.ready = is_ready
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

