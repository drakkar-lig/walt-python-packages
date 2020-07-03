import re
from walt.server.threads.main.filesystem import Filesystem

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

ERROR_BAD_IMAGE_NAME='''\
Bad name: expected format is <name> or <name>:<tag>.
Only lowercase letters, digits and dash(-) characters are allowed in <name> and <tag>.
'''

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
    def __init__(self, store, fullname):
        self.store = store
        self.db = store.db
        self.docker = store.docker
        self.rename(fullname)
        self.filesystem = Filesystem(FS_CMD_PATTERN % dict(image = self.fullname))
        self.task_label = None
    def rename(self, fullname):
        self.fullname, self.user, self.name = parse_image_fullname(fullname)
    @property
    def metadata(self):
        return self.docker.local.get_metadata(self.fullname)
    @property
    def image_id(self):
        return self.metadata['image_id']
    @property
    def created_at(self):
        return self.metadata['created_at']
    @property
    def labels(self):
        return self.metadata['labels']
    @property
    def editable(self):
        return self.metadata['editable']
    @property
    def ready(self):
        return self.db.select_unique('images', fullname=self.fullname).ready
    @ready.setter
    def ready(self, is_ready):
        self.db.update('images', 'fullname', fullname=self.fullname, ready=is_ready)
        self.db.commit()
    def get_node_models(self):
        if self.labels is None:
            return None
        if 'walt.node.models' not in self.labels:
            return None
        return self.labels['walt.node.models'].split(',')
    @property
    def mount_path(self):
        return self.store.get_mount_path(self.image_id)
    @property
    def in_use(self):
        return self.store.image_is_used(self.fullname)
    @property
    def mounted(self):
        return self.store.image_is_mounted(self.image_id)
    def squash(self):
        self.docker.local.squash(self.fullname)
