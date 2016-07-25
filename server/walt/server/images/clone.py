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

MSG_IMAGE_NOT_COMPATIBLE="""\
The WalT software embedded in %(link)s is not compatible with the WalT server, and cloning
it would overwrite your image %(tag)s, which is currently deployed.
This is not allowed, unless you rerun with --update option.
Type "walt --help-about compatibility" for information about compatibility matters.
Aborted.
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
    return 'clone-temp/walt-node:' + str(uuid.uuid4()).split('-')[0]

# workflow functions
# ------------------

# Note: we save initial images, because:
# * in some cases we want to retain the filesystem layers otherwise we
# would need to download them again (case of the overwrite of a server
# image with its updated hub version)
# * if we detect an issue late in the workflow, we can still restore them.
def save_initial_images(saved_images, ws_image_fullname, remote_image_fullname,
                            existing_server_image, existing_ws_image,
                            docker, **args):
    initial_image_fullnames = set()
    for fullname, exists in (   (ws_image_fullname, existing_ws_image),
                                (remote_image_fullname, existing_server_image)):
        if exists:
            initial_image_fullnames.add(fullname)
    for image_fullname in initial_image_fullnames:
        image_backup = get_temp_image_fullname()
        docker.tag(image_fullname, image_backup)
        saved_images[image_fullname] = image_backup
        images_to_be_removed.add(image_backup)  # after the workflow is done

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

def verify_compatibility_issue(image_store, requester, clonable_link,
                    ws_image_fullname, remote_image_fullname, auto_update,
                    **args):
    if auto_update:
        return  # no problem
    ws_image = image_store[ws_image_fullname]
    if not ws_image.mounted:
        return  # no problem
    # there is a risk of overwritting the mounted ws image with
    # a target image that embeds incompatible walt software.
    # we will have to mount the target image in order to check
    # its compatibility.
    # we use a new docker tag pointing to this image, in order to
    # avoid interfering with an existing image.
    tmp_image_fullname = get_temp_image_fullname()
    docker.tag(remote_image_fullname, tmp_image_fullname)
    image_store.register_image(tmp_image_fullname, True)
    tmp_image = image_store[tmp_image_fullname]
    compatibility = tmp_image.check_server_compatibility()
    image_store.remove(tmp_image_fullname)
    docker.untag(tmp_image_fullname)
    if compatibility != 0:
        requester.stderr.write(MSG_IMAGE_NOT_COMPATIBLE)
        return False

def remove_ws_image(docker, ws_image_fullname, **args):
    docker.untag(ws_image_fullname)

def remove_server_image(docker, remote_image_fullname, **args):
    docker.untag(remote_image_fullname)

def restore_initial_ws_image(docker, ws_image_fullname,
                                saved_images, **args):
    ws_image_backup = saved_images[ws_image_fullname]
    docker.tag(ws_image_backup, ws_image_fullname)

def restore_initial_server_image(docker, remote_image_fullname,
                                saved_images, **args):
    server_image_backup = saved_images[remote_image_fullname]
    docker.tag(server_image_backup, remote_image_fullname)

def tag_server_image_to_requester(docker,
                ws_image_fullname, remote_image_fullname, **args):
    docker.tag(remote_image_fullname, ws_image_fullname)

def pull_hub_image(docker, requester, remote_image_fullname, **args):
    docker.pull(remote_image_fullname, requester.stdout)

def update_walt_image(image_store, ws_image_fullname, auto_update, **args):
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
            image_store.update_image_mounts(auto_update = auto_update)
    else:
        # add this new image in the store
        image_store.register_image(ws_image_fullname, True)

def cleanup(docker, images_to_be_removed, **args):
    while len(images_to_be_removed) > 0:
        docker.untag(images_to_be_removed.pop())

# workflow management functions
# -----------------------------
def workflow_exit(**context):
    return False

def workflow_if(condition_func, workflow_if_true, workflow_if_false):
    def workflow_if_instance(**context):
        if condition_func(**context) != False:
            return workflow_run(workflow_if_true, **context)
        else:
            return workflow_run(workflow_if_false, **context)
    return workflow_if_instance

def workflow_run(workflow, **context):
    for f in workflow:
        res = f(**context)
        if res == False:
            return False # issue, stop here

# walt image clone implementation
# -------------------------------
def perform_clone(requester, docker, clonable_link, image_store, force, auto_update):
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
        (LOCATION_WALT_SERVER, True, True, False):  [ verify_overwrite, verify_compatibility_issue,
                                                        remove_ws_image, tag_server_image_to_requester ],
        (LOCATION_WALT_SERVER, True, True, True):   [ error_image_belongs_to_ws ],

        (LOCATION_DOCKER_HUB, False, False, False): [ pull_hub_image, tag_server_image_to_requester, remove_server_image ],
        (LOCATION_DOCKER_HUB, False, True, False):  [ verify_overwrite, pull_hub_image, verify_compatibility_issue,
                                                        remove_ws_image, \
                                                        tag_server_image_to_requester, remove_server_image ],
        (LOCATION_DOCKER_HUB, True, False, False):  [ remove_server_image, pull_hub_image,
                                                        tag_server_image_to_requester, remove_server_image,
                                                        restore_initial_server_image ],
        (LOCATION_DOCKER_HUB, True, True, False):   [ verify_overwrite,
                                                        remove_server_image, pull_hub_image,
                                                        workflow_if(verify_compatibility_issue,
                                                            # ok
                                                            [ remove_ws_image, tag_server_image_to_requester,
                                                              remove_server_image, restore_initial_server_image ],
                                                            # compatibility issue with pulled image, restore things
                                                            [ remove_server_image, restore_initial_server_image,
                                                              workflow_exit ]) ],
        (LOCATION_DOCKER_HUB, False, False, True):  [ pull_hub_image ],
        (LOCATION_DOCKER_HUB, True, True, True):    [ verify_overwrite, remove_ws_image,
                                                        pull_hub_image,
                                                        workflow_if(verify_compatibility_issue,
                                                            # ok, we are all done
                                                            [ ],
                                                            # compatibility issue with pulled image, restore things
                                                            [ remove_ws_image, restore_saved_ws_image,
                                                              workflow_exit ]) ],
    }
    workflow = [ save_initial_images ]     # this is always called first
    workflow += workflow_selector[(remote_location, existing_server_image, existing_ws_image, same_user)]
    workflow += [ update_walt_image ]      # this is always called at the end (unless an error occurs before)
    print 'clone workflow is:', ', '.join([ f.__name__ for f in workflow ])

    # proceed
    # -------
    context = dict(
        ws_image_fullname = "%s/walt-node:%s" % (requester.username, remote_tag),
        remote_image_fullname = "%s/walt-node:%s" % (remote_user, remote_tag),
        existing_server_image = existing_server_image,
        existing_ws_image = existing_ws_image,
        image_store = image_store,
        docker = docker,
        requester = requester,
        force = force,
        auto_update = auto_update,
        saved_images = {},
        images_to_be_removed = set(),
        clonable_link = clonable_link
    )

    res = workflow_run(workflow, **context)

    # this is always called, even if an error occured in the workflow
    cleanup(**context)

    if res:
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

