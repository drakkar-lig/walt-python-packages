import os, re, time, shutil
from plumbum.cmd import chroot
from walt.server.network.tools import get_server_ip
from walt.server.filesystem import Filesystem
from walt.common.tools import \
        failsafe_makedirs, succeeds

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
SERVER_PUBKEY_PATH = '/root/.ssh/id_dsa.pub'
HOSTS_FILE_CONTENT="""\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
"""
SERVER_SPEC_PATH='/etc/walt/server.spec'

def get_mount_path(image_fullname):
    mount_path, dummy = get_mount_info(image_fullname)
    return mount_path

def get_mount_info(image_fullname):
    sub_path = re.sub('[^a-zA-Z0-9/-]+', '_', re.sub(':', '/', image_fullname))
    return IMAGE_MOUNT_PATH % sub_path, IMAGE_DIFF_PATH % sub_path

def get_server_pubkey():
    with open(SERVER_PUBKEY_PATH, 'r') as f:
        return f.read()

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
    server_pubkey = get_server_pubkey()
    def __init__(self, docker, fullname):
        self.docker = docker
        self.rename(fullname)
        self.created_at = None
        self.ready = False
        self.mount_path = None
        self.mounted = False
        self.top_layer_id = None
        self.server_ip = get_server_ip()
        self.filesystem = Filesystem(FS_CMD_PATTERN % dict(image = self.fullname))
    def rename(self, fullname):
        self.fullname, self.name, dummy, self.user, self.tag = \
            parse_image_fullname(fullname)
    def set_ready(self, is_ready):
        if is_ready and not self.ready:
            # image just became ready, get the creation time and image id from docker
            self.created_at = self.docker.get_creation_time(self.fullname)
            self.update_top_layer_id()
        self.ready = is_ready
    def update_top_layer_id(self):
        self.top_layer_id = self.docker.get_top_layer_id(self.fullname)
    def __del__(self):
        if self.mounted:
            self.unmount()
    def get_mount_info(self):
        return get_mount_info(self.fullname)
    def mount(self):
        print 'Mounting %s...' % self.fullname
        self.mount_path, self.diff_path = self.get_mount_info()
        failsafe_makedirs(self.mount_path)
        failsafe_makedirs(self.diff_path)
        self.docker.image_mount(self.top_layer_id, self.diff_path, self.mount_path)
        if os.path.exists(SERVER_SPEC_PATH):
            target_path = self.mount_path + SERVER_SPEC_PATH
            failsafe_makedirs(os.path.dirname(target_path))
            shutil.copy(SERVER_SPEC_PATH, target_path)
        install_text = chroot(self.mount_path,
                'walt-node-install', self.server_ip, NodeImage.server_pubkey).strip()
        if len(install_text) > 0:
            print install_text
        self.create_hosts_file()
        self.mounted = True
        print 'Mounting %s... done' % self.fullname
    def unmount(self):
        print 'Un-mounting %s...' % self.fullname,
        while not succeeds('umount %s 2>/dev/null' % self.mount_path):
            time.sleep(0.1)
        shutil.rmtree(self.diff_path)
        os.rmdir(self.mount_path)
        self.mounted = False
        print 'done'
    def create_hosts_file(self):
        # since file /etc/hosts is managed by docker,
        # it appears empty on the bind mount.
        # let's create it appropriately.
        with open(self.mount_path + '/etc/hosts', 'w') as f:
            f.write(HOSTS_FILE_CONTENT)

