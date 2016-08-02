import os, re, time, shutil, shlex
from plumbum.cmd import chroot
from walt.server.thread.main.network.tools import get_server_ip
from walt.server.thread.main.filesystem import Filesystem
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
SERVER_PUBKEY_PATH = '/root/.ssh/id_dsa.pub'
HOSTS_FILE_CONTENT="""\
127.0.0.1   localhost
::1     localhost ip6-localhost ip6-loopback
ff02::1     ip6-allnodes
ff02::2     ip6-allrouters
"""
SERVER_SPEC_PATH='/etc/walt/server.spec'

MSG_IMAGE_NOT_COMPATIBLE="""\
The WalT software embedded in %(tag)s is too %(image_status)s. It is not compatible with the WalT server.
Type "walt --help-about compatibility" for information about upgrade & downgrade options.
Aborted.
"""

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
    server_pubkey = None
    def __init__(self, docker, fullname):
        if NodeImage.server_pubkey == None:
            NodeImage.server_pubkey = get_server_pubkey()
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
    def get_versioning_numbers(self):
        with self.ensure_temporary_mount():
            version_check_available = self.chroot('which walt-node-versioning-getnumbers')
            if len(version_check_available) == 0:
                # image was built before the version management code
                return (0, 0)
            else:
                version_check_result = self.chroot('walt-node-versioning-getnumbers')
                return eval(version_check_result)
    def update_walt_software(self):
        assert (not self.mounted), 'update_walt_software() called when the image is mounted!'
        self.chroot('pip install --upgrade "walt-nodeselector==%d.*"' % \
                        API_VERSIONING['NS'][0])
    def check_server_compatibility(self, requester, auto_update):
        srv_ns_api, srv_upload = (API_VERSIONING['NS'][0], UPLOAD)
        node_ns_api, node_upload = self.get_versioning_numbers()
        if srv_ns_api == node_ns_api:
            compatibility = 0
        else:
            if node_upload < srv_upload:
                compatibility = -1
                image_status = 'old'
            else:
                compatibility = 1
                image_status = 'recent'
            if requester and not auto_update:
                requester.stderr.write(MSG_IMAGE_NOT_COMPATIBLE % dict(
                    tag = self.tag,
                    image_status = image_status
                ))
            print 'Incompatibility server <-> image detected.'
        return compatibility
    def os_mount(self):
        self.mount_path, self.diff_path = self.get_mount_info()
        failsafe_makedirs(self.mount_path)
        failsafe_makedirs(self.diff_path)
        self.docker.image_mount(self.top_layer_id, self.diff_path, self.mount_path)
        self.mounted = True
    def mount(self, requester = None, auto_update = False):
        print 'Mounting %s...' % self.fullname
        self.os_mount()
        compatibility = self.check_server_compatibility(requester, auto_update)
        if compatibility != 0:
            if auto_update:
                self.os_unmount()
                self.update_walt_software()
                self.os_mount()
            else:
                if requester == None and auto_update == False:
                    raise RuntimeError("Programming error: Image mounting with auto_update disabled " + \
                                        "and no requester to warn about the incompatibility issue.")
                # cannot go any further
                self.os_unmount()
                return
        if os.path.exists(SERVER_SPEC_PATH):
            target_path = self.mount_path + SERVER_SPEC_PATH
            failsafe_makedirs(os.path.dirname(target_path))
            shutil.copy(SERVER_SPEC_PATH, target_path)
        install_text = self.chroot('walt-node-install %(server_ip)s %(server_pubkey)s' % \
                            dict(server_ip = self.server_ip, 
                                 server_pubkey = NodeImage.server_pubkey))
        if len(install_text) > 0:
            print install_text
        self.create_hosts_file()
        print 'Mounting %s... done' % self.fullname
    def os_unmount(self):
        while not succeeds('umount %s 2>/dev/null' % self.mount_path):
            time.sleep(0.1)
        shutil.rmtree(self.diff_path)
        os.rmdir(self.mount_path)
        self.mounted = False
    def unmount(self):
        print 'Un-mounting %s...' % self.fullname,
        self.os_unmount()
        print 'done'
    def create_hosts_file(self):
        # since file /etc/hosts is managed by docker,
        # it appears empty on the bind mount.
        # let's create it appropriately.
        with open(self.mount_path + '/etc/hosts', 'w') as f:
            f.write(HOSTS_FILE_CONTENT)

