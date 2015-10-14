import os, re, time
from plumbum.cmd import mount, umount, findmnt
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
SERVER_PUBKEY_PATH = '/root/.ssh/id_dsa.pub'
HOSTS_FILE_CONTENT="""\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
"""

def get_mount_path(image_fullname):
    return IMAGE_MOUNT_PATH % \
            re.sub('[^a-zA-Z0-9/-]+', '_', re.sub(':', '/', image_fullname))

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
        self.created_at = docker.get_creation_time(fullname)
        self.cid = None
        self.mount_path = None
        self.mounted = False
        self.server_ip = get_server_ip()
        self.filesystem = Filesystem(FS_CMD_PATTERN % dict(image = self.fullname))
    def rename(self, fullname):
        self.fullname, self.name, dummy, self.user, self.tag = \
            parse_image_fullname(fullname)
    def __del__(self):
        if self.mounted:
            self.unmount()
    def get_mount_path(self):
        return get_mount_path(self.fullname)
    def mount(self):
        print 'Mounting %s...' % self.fullname,
        self.mount_path = self.get_mount_path()
        failsafe_makedirs(self.mount_path)
        cmd = 'walt-node-install %s "%s"' % \
                    (self.server_ip, NodeImage.server_pubkey)
        self.cid = self.docker.start_container(self.fullname, cmd)
        self.bind_mount()
        self.create_hosts_file()
        self.mounted = True
        print 'done'
    def unmount(self):
        print 'Un-mounting %s...' % self.fullname,
        while not succeeds('umount %s 2>/dev/null' % self.mount_path):
            time.sleep(0.1)
        self.docker.stop_container(self.cid)
        os.rmdir(self.mount_path)
        self.mounted = False
        print 'done'
    def create_hosts_file(self):
        # since file /etc/hosts is managed by docker,
        # it appears empty on the bind mount.
        # let's create it appropriately.
        with open(self.mount_path + '/etc/hosts', 'w') as f:
            f.write(HOSTS_FILE_CONTENT)
    def list_mountpoints(self):
        return findmnt('-nlo', 'TARGET').splitlines()
    def get_mount_point(self):
        return [ line for line in self.list_mountpoints() \
                        if line.find(self.cid) != -1 ][0]
    def bind_mount(self):
        mount('-o', 'bind', self.get_mount_point(), self.mount_path)

