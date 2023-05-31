from __future__ import annotations

import re
import typing

from walt.common.tools import parse_image_fullname

if typing.TYPE_CHECKING:
    from walt.server.processes.main.images.store import NodeImageStore

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
# * walt knows whether or not an image is a walt
#   image by checking if it has a builtin label
#   'walt.node.models=<list-of-models>'.
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
# Since version 5, walt has its own storage of walt images,
# different than the storage used by docker tool on the machine.
#
# Thus clonable / searchable images may either be on the docker
# hub, or local on the machine but managed by the docker daemon.
# In the table above, category 'In the docker hub' can actually
# match those two categories of images.
#
# In order to clone an image, the user must specify
# a 'clonable image link' as an argument to 'walt image clone'.
# Such a clonable link is formatted as follows:
# [walt|hub|docker]:<user>/<name>

ERROR_BAD_IMAGE_NAME = """\
Bad name: expected format is <name> or <name>:<tag>.
Only lowercase letters, digits and dash(-) characters are allowed in <name> and <tag>.
"""

ERROR_DEFAULT_IMAGE_RESERVED = """\
Sorry 'default' is a reserved keyword.
"""


def check_alnum_dash(token):
    return re.match(r"^[a-zA-Z0-9\-]+$", token)


def validate_image_name(requester, image_name):
    if image_name == "default":
        requester.stderr.write(ERROR_DEFAULT_IMAGE_RESERVED)
        return False
    if image_name.count(":") in (0, 1) and re.match(
        r"^[a-z0-9\-]+$", image_name.replace(":", "")
    ):
        return True  # ok
    requester.stderr.write(ERROR_BAD_IMAGE_NAME)
    return False


class NodeImage(object):
    def __init__(self, store: NodeImageStore, fullname):
        self.store = store
        self.db = store.db
        self.registry = store.registry
        self.rename(fullname)
        self.task_label = None

    @property
    def filesystem(self):
        return self.store.get_filesystem(self.image_id)

    def rename(self, fullname):
        self.fullname, self.user, self.name = parse_image_fullname(fullname)

    @property
    def metadata(self):
        return self.registry.get_metadata(self.fullname)

    @property
    def image_id(self):
        return self.metadata["image_id"]

    @property
    def created_at(self):
        return self.metadata["created_at"]

    @property
    def labels(self):
        return self.metadata["labels"]

    @property
    def node_models(self):
        return self.metadata["node_models"]

    @property
    def node_models_desc(self):
        return self.metadata["node_models_desc"]

    @property
    def editable(self):
        return self.metadata["editable"]

    def get_node_models(self):
        return self.node_models

    def get_labels(self):
        return self.labels

    @property
    def mount_path(self):
        return self.store.get_mount_path(self.image_id)

    def in_use(self):
        return self.store.image_is_used(self.fullname)

    @property
    def mounted(self):
        return self.store.image_is_mounted(self.image_id)

    def squash(self):
        self.registry.squash(self.fullname)
