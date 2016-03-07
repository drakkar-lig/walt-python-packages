import requests, uuid
from walt.server.images.search import \
        Search, \
        LOCATION_WALT_SERVER, LOCATION_DOCKER_HUB, \
        LOCATION_LABEL, LOCATION_PER_LABEL

# About terminology: See comment about it in image.py.

# Implementation notes:
# walt image clone relies on a complex process.
# depending on what we are cloning, who we are,
# what are the existing docker images and whether
# we want to overwrite these existing images or not,
# we have many cases to think about.
# that's why we have organised this process as follows:
# 1- we search for existing images
# 2- we perform basic validation of the request
# 3- we compute a workflow (a list of function calls)
# 4- we execute this workflow.
#
# (also note that since docker downloads may take a long time,
# we also have to implement this in an asynchronous task.)

MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS = """\
Invalid clonable image link.
Images of the form 'server:%s/<image_name>' already belong to
your working set and thus are not clonable.
"""
MSG_USE_FORCE = """\
If this is what you want, rerun with --force:
$ walt image clone --force %s
"""
MSG_INVALID_CLONABLE_LINK = """\
Invalid clonable image link. Format must be:
[server|hub]:<user>/<image_name>
(tip: walt image search [<keyword>])
"""

# Subroutines
# -----------
def parse_clonable_link(requester, clonable_link):
    bad = False
    parts = clonable_link.split(':')
    if len(parts) != 2:
        bad = True
    if not bad:
        location = parts[0]
        if location not in LOCATION_LABEL.values():
            bad = True
    if not bad:
        parts = parts[1].split('/')
        if len(parts) != 2:
            bad = True
    if not bad:
        return (LOCATION_PER_LABEL[location],
                parts[0],
                parts[1])
    if bad:
        requester.stderr.write(MSG_INVALID_CLONABLE_LINK)
        return None, None, None

def get_temp_image_fullname():
    return 'walt/clone-temp:' + str(uuid.uuid4()).split('-')[0]

# we delay the removal of images because:
# * in some case we want to retain the filesystem layers otherwise we
#   would need to download them again (case of the overwrite of a server
#   image with its updated hub version)
# * walt may have it mounted
# They will be really removed when the cleanup() function is called.
def hide_image(image_fullname, docker, images_to_be_removed, **args):
    image_temp_copy = get_temp_image_fullname()
    docker.tag(image_fullname, image_temp_copy)
    docker.untag(image_fullname)
    images_to_be_removed.add(image_temp_copy)

# workflow functions
# ------------------
def error_image_belongs_to_ws(requester, **args):
    requester.stderr.write(
        MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS % requester.username)
    return False

def verify_overwrite(image_store, requester, clonable_link,
                    ws_image_fullname, force, **args):
    if not force:
        image_store.warn_overwrite_image(requester, ws_image_fullname)
        requester.stderr.write(MSG_USE_FORCE % clonable_link)
        return False

def remove_ws_image(ws_image_fullname, **args):
    hide_image(ws_image_fullname, **args)

def remove_server_image(remote_image_fullname, **args):
    hide_image(remote_image_fullname, **args)

def save_server_image(docker, remote_image_fullname, saved_server_image, **args):
    server_image_copy = get_temp_image_fullname()
    docker.tag(remote_image_fullname, server_image_copy)
    saved_server_image.add(server_image_copy)

def restore_saved_server_image(docker, remote_image_fullname,
                                saved_server_image, **args):
    server_image_copy = saved_server_image.pop()
    docker.tag(server_image_copy, remote_image_fullname)
    docker.untag(server_image_copy)

def tag_server_image_to_requester(docker,
                ws_image_fullname, remote_image_fullname, **args):
    docker.tag(remote_image_fullname, ws_image_fullname)

def pull_hub_image(docker, requester, remote_image_fullname, **args):
    docker.pull(remote_image_fullname, requester.stdout)

def update_walt_image(image_store, ws_image_fullname, **args):
    if ws_image_fullname in image_store:
        # an image with the target name exists
        existing_dest_image = image_store[ws_image_fullname]
        # if image is mounted, umount/mount it in order to make
        # the nodes reboot with the new version
        need_mount_umount = existing_dest_image.mounted
        if need_mount_umount:
            # umount
            image_store.umount_used_image(existing_dest_image)
        # image has changed, update the top filesystem layer it
        # points to.
        existing_dest_image.update_top_layer_id()
        if need_mount_umount:
            # re-mount
            image_store.update_image_mounts()
    else:
        # add this new image in the store
        image_store.register_image(ws_image_fullname, True)

def cleanup(docker, images_to_be_removed, **args):
    while len(images_to_be_removed) > 0:
        docker.untag(images_to_be_removed.pop())

# walt image clone implementation
# -------------------------------
def perform_clone(requester, docker, clonable_link, image_store, force):
    remote_location, remote_user, remote_tag = parse_clonable_link(
                                                requester, clonable_link)
    if remote_location == None:
        return # error already reported
    # actually we should validate the 3 components (user, tag and location), but
    # let's get a larger set of information (especially about other existing
    # images with the same tag, because we should take care not to overwrite
    # them)
    def validate(user, tag, location):
        return tag == remote_tag
    # search
    result = Search(docker, requester, 'Validating...').search(validate)
    # check that the requested image is in the resultset
    if remote_location not in result[remote_tag][remote_user]:
        requester.stderr.write(
            'No such remote image. Use walt image search <keyword>.\n')
        return

    # compute the workflow
    # --------------------
    existing_server_image = (LOCATION_WALT_SERVER in result[remote_tag][remote_user])
    existing_ws_image = (LOCATION_WALT_SERVER in result[remote_tag][requester.username])
    same_user = (requester.username == remote_user)
    # obvious facts:
    # * if remote_location is LOCATION_WALT_SERVER, existing_server_image is True
    # * if same_user is True, existing_server_image == existing_ws_image
    # that's why not all workflow entries are possible.
    workflow_selector = {
        # remote_location, existing_server_image, existing_ws_image, same_user
        (LOCATION_WALT_SERVER, True, False, False): [ tag_server_image_to_requester ],
        (LOCATION_WALT_SERVER, True, True, False):  [ verify_overwrite, remove_ws_image, tag_server_image_to_requester ],
        (LOCATION_WALT_SERVER, True, True, True):   [ error_image_belongs_to_ws ],

        (LOCATION_DOCKER_HUB, False, False, False): [ pull_hub_image, tag_server_image_to_requester, remove_server_image ],
        (LOCATION_DOCKER_HUB, False, True, False):  [ verify_overwrite, remove_ws_image, pull_hub_image, \
                                                        tag_server_image_to_requester, remove_server_image ],
        (LOCATION_DOCKER_HUB, True, False, False):  [ save_server_image, remove_server_image, pull_hub_image, \
                                                        tag_server_image_to_requester, remove_server_image, \
                                                        restore_saved_server_image ],
        (LOCATION_DOCKER_HUB, True, True, False):   [ verify_overwrite, remove_ws_image, \
                                                        save_server_image, remove_server_image, pull_hub_image, \
                                                        tag_server_image_to_requester, remove_server_image, \
                                                        restore_saved_server_image ],
        (LOCATION_DOCKER_HUB, False, False, True):  [ pull_hub_image ],
        (LOCATION_DOCKER_HUB, True, True, True):    [ verify_overwrite, remove_ws_image, pull_hub_image ]
    }
    workflow = workflow_selector[(remote_location, existing_server_image, existing_ws_image, same_user)]
    workflow += [ update_walt_image, cleanup ]      # these 2 are always called
    print 'clone workflow is:', ', '.join([ f.__name__ for f in workflow ])

    # proceed
    # -------
    context = dict(
        ws_image_fullname = "%s/walt-node:%s" % (requester.username, remote_tag),
        remote_image_fullname = "%s/walt-node:%s" % (remote_user, remote_tag),
        image_store = image_store,
        docker = docker,
        requester = requester,
        force = force,
        saved_server_image = set(), # need a mutable object
        images_to_be_removed = set(),
        clonable_link = clonable_link
    )

    for f in workflow:
        res = f(**context)
        if res == False:
            return  # issue, stop here

    requester.stdout.write('Done.\n')

class CloneTask(object):
    def __init__(self, q, requester, **kwargs):
        self.response_q = q
        self.requester = requester
        self.kwargs = kwargs
    def perform(self):
        perform_clone(  requester = self.requester,
                        **self.kwargs)
    def handle_result(self, res):
        if isinstance(res, requests.exceptions.RequestException):
            print repr(res)
            self.requester.stderr.write(
                'Network connection to docker hub failed.\n')
            res = None
        elif isinstance(res, Exception):
            raise res   # unexpected
        self.response_q.put(res)

# this implements walt image clone
def clone(blocking, **kwargs):
    blocking.do(CloneTask(**kwargs))

