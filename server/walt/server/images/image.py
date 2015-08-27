import os, re, sys, requests, shlex, time
from datetime import datetime
from plumbum.cmd import mount, umount, findmnt
from walt.server.network.tools import get_server_ip
from walt.common.tools import \
        failsafe_makedirs, succeeds

# Terminology:
#
# - on the server side source code:
#   we follow the *docker terminology*
#
#   <user>/<repository>:<tag>
#   <-- name --------->
#   <-- fullname ----------->
#
#   note: all walt images have <repository>='walt-node',
#   which allows to find them.
#
# - on the client side source code:
#   we follow the *walt user point of view*
#   the 'name' of an image is actually the docker <tag> only.

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
    image_user, dummy = image_name.split('/')
    return image_fullname, image_name, image_user, image_tag

class NodeImage(object):
    server_pubkey = get_server_pubkey()
    REMOTE = 0
    LOCAL = 1
    def __init__(self, c, fullname, state):
        self.c = c
        self.rename(fullname)
        self.set_created_at()
        self.state = state
        self.cid = None
        self.mount_path = None
        self.mounted = False
        self.server_ip = get_server_ip()
    def rename(self, fullname):
        self.fullname, self.name, self.user, self.tag = \
            parse_image_fullname(fullname)
    def set_created_at(self):
        # created_at is only available on local images
        # (downloaded or created locally)
        self.created_at = None
        for i in self.c.images():
            if self.fullname in i['RepoTags']:
                self.created_at = datetime.fromtimestamp(i['Created'])
    def __del__(self):
        if self.mounted:
            self.unmount()
    def download(self):
        for idx, line in enumerate(
                    self.c.pull(
                        self.name,
                        tag=requests.utils.quote(self.tag),
                        stream=True)):
            progress = "-/|\\"[idx % 4]
            sys.stdout.write('Downloading image %s... %s\r' % \
                                (self.fullname, progress))
            sys.stdout.flush()
        sys.stdout.write('\n')
        self.state = NodeImage.LOCAL
    def get_mount_path(self):
        return get_mount_path(self.fullname)
    def docker_command_split(self, cmd):
        args = shlex.split(cmd)
        return dict(
            entrypoint=args[0],
            command=args[1:]
        )
    def mount(self):
        print 'Mounting %s...' % self.fullname,
        self.mount_path = self.get_mount_path()
        failsafe_makedirs(self.mount_path)
        if self.state == NodeImage.REMOTE:
            self.download()
        params = dict(image=self.fullname)
        params.update(self.docker_command_split(
            'walt-node-install %s "%s"' % \
                    (self.server_ip, NodeImage.server_pubkey)))
        self.cid = self.c.create_container(**params).get('Id')
        self.c.start(container=self.cid)
        self.bind_mount()
        self.create_hosts_file()
        self.mounted = True
        print 'done'
    def unmount(self):
        print 'Un-mounting %s...' % self.fullname,
        while not succeeds('umount %s 2>/dev/null' % self.mount_path):
            time.sleep(0.1)
        self.c.kill(container=self.cid)
        self.c.wait(container=self.cid)
        self.c.remove_container(container=self.cid)
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

