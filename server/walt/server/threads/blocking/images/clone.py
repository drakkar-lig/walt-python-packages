import requests, uuid
from walt.server.threads.blocking.images.search import \
        LOCATION_WALT_SERVER, LOCATION_DOCKER_HUB, \
        LOCATION_LABEL, LOCATION_PER_LABEL
from walt.server.threads.blocking.images.metadata import \
            pull_user_metadata

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
[server|hub]:<user>/<image_name>[:<tag>]
(tip: walt image search [<keyword>])
"""

# Subroutines
# -----------
def parse_clonable_link(requester, clonable_link):
    bad = False
    parts = clonable_link.split(':', 1)
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
        user, image_name = parts
        parts = image_name.split(':')
        if len(parts) == 1:
            image_name += ':latest'
        elif len(parts) != 2:
            bad = True
    if not bad:
        return (LOCATION_PER_LABEL[location], user, image_name)
    if bad:
        requester.stderr.write(MSG_INVALID_CLONABLE_LINK)
        return None, None, None

def get_temp_image_fullname():
    return 'clone-temp/walt-image:' + str(uuid.uuid4()).split('-')[0]

def image_exists(docker, image_store, location, fullname):
    if location == LOCATION_WALT_SERVER:
        return fullname in image_store
    else:   # Hub
        user = fullname.split('/')[0]
        user_metadata = pull_user_metadata(docker, user)
        return fullname in user_metadata['walt.user.images']

# workflow functions
# ------------------

# Note: we save initial images, because:
# * in some cases we want to retain the filesystem layers otherwise we
# would need to download them again (case of the overwrite of a server
# image with its updated hub version)
# * if we detect an issue late in the workflow, we can still restore them.
def save_initial_images(images_to_be_removed, saved_images,
                        ws_image_fullname, remote_image_fullname,
                        existing_server_image, existing_ws_image,
                        docker, **args):
    initial_image_fullnames = set()
    for fullname, exists in (   (ws_image_fullname, existing_ws_image),
                                (remote_image_fullname, existing_server_image)):
        if exists:
            initial_image_fullnames.add(fullname)
    for image_fullname in initial_image_fullnames:
        image_backup = get_temp_image_fullname()
        docker.local.tag(image_fullname, image_backup)
        saved_images[image_fullname] = image_backup
        images_to_be_removed.add(image_backup)  # after the workflow is done

def error_image_belongs_to_ws(requester, username, **args):
    requester.stderr.write(
        MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS % username)
    return False

def verify_overwrite(image_store, requester, clonable_link,
                    ws_image_fullname, force, **args):
    if not force:
        image_store.warn_overwrite_image(requester, ws_image_fullname)
        requester.stderr.write(MSG_USE_FORCE % clonable_link)
        return False

# we should verify that the image is compatible with the node types
# currently using it
def verify_compatibility_issue(image_store, requester, clonable_link,
                    ws_image_fullname, remote_image_fullname,
                    docker, **args):
    ws_image = image_store[ws_image_fullname]
    if not ws_image.mounted:
        return  # no problem
    # there is a risk of overwritting the mounted ws image with
    # a target image that is incompatible.
    # we will have to mount the target image in order to check
    # its compatibility.
    # we use a new docker tag pointing to this image, in order to
    # avoid interfering with an existing image.
    tmp_image_fullname = get_temp_image_fullname()
    docker.local.tag(remote_image_fullname, tmp_image_fullname)
    image_store.register_image(tmp_image_fullname, True)
    tmp_image = image_store[tmp_image_fullname]
    compatible = True   # for now
    image_store.remove(tmp_image_fullname)
    docker.local.untag(tmp_image_fullname)
    if not compatible:
        pass # do something
        return False

def remove_ws_image(docker, ws_image_fullname, **args):
    docker.local.untag(ws_image_fullname)

def remove_server_image(docker, remote_image_fullname, **args):
    docker.local.untag(remote_image_fullname)

def restore_initial_ws_image(docker, ws_image_fullname,
                                saved_images, **args):
    ws_image_backup = saved_images[ws_image_fullname]
    docker.local.tag(ws_image_backup, ws_image_fullname)

def restore_initial_server_image(docker, remote_image_fullname,
                                saved_images, **args):
    server_image_backup = saved_images[remote_image_fullname]
    docker.local.tag(server_image_backup, remote_image_fullname)

def tag_server_image_to_requester(docker,
                ws_image_fullname, remote_image_fullname, **args):
    docker.local.tag(remote_image_fullname, ws_image_fullname)

def pull_hub_image(docker, requester, remote_image_fullname, **args):
    docker.hub.pull(remote_image_fullname, requester)

def update_walt_image(image_store, ws_image_fullname, **args):
    if ws_image_fullname in image_store:
        # an image with the target name exists
        existing_dest_image = image_store[ws_image_fullname]
        # if image is mounted, umount/mount it in order to make
        # the nodes reboot with the new version
        if existing_dest_image.mounted:
            # umount
            image_store.umount_used_image(existing_dest_image)
            # re-mount
            image_store.update_image_mounts()
    else:
        # add this new image in the store
        image_store.register_image(ws_image_fullname, True)

def cleanup(docker, images_to_be_removed, **args):
    while len(images_to_be_removed) > 0:
        docker.local.untag(images_to_be_removed.pop())

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
def perform_clone(requester, docker, clonable_link, image_store, force):
    username = requester.get_username()
    if not username:
        return # client already disconnected, give up
    remote_location, remote_user, remote_image_name = parse_clonable_link(
                                                requester, clonable_link)
    if remote_location == None:
        return # error already reported

    ws_image_fullname = "%s/%s" % (username, remote_image_name)
    remote_image_fullname = "%s/%s" % (remote_user, remote_image_name)

    # check that the requested image really exists
    if not image_exists(
            docker, image_store, remote_location, remote_image_fullname):
        requester.stderr.write(
            'No such remote image. Use walt image search <keyword>.\n')
        return

    # analyse our context
    existing_server_image = image_exists(
            docker, image_store, LOCATION_WALT_SERVER, remote_image_fullname)
    existing_ws_image = image_exists(
            docker, image_store, LOCATION_WALT_SERVER, ws_image_fullname)
    same_user = (username == remote_user)

    # compute the workflow
    # --------------------
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
                                                            [ remove_ws_image, restore_initial_ws_image,
                                                              workflow_exit ]) ],
    }
    workflow = [ save_initial_images ]     # this is always called first
    workflow += workflow_selector[(remote_location, existing_server_image, existing_ws_image, same_user)]
    workflow += [ update_walt_image ]      # this is always called at the end (unless an error occurs before)
    print 'clone workflow is:', ', '.join([ f.__name__ for f in workflow ])

    # proceed
    # -------
    context = dict(
        username = username,
        ws_image_fullname = ws_image_fullname,
        remote_image_fullname = remote_image_fullname,
        existing_server_image = existing_server_image,
        existing_ws_image = existing_ws_image,
        image_store = image_store,
        docker = docker,
        requester = requester,
        force = force,
        saved_images = {},
        images_to_be_removed = set(),
        clonable_link = clonable_link
    )

    res = workflow_run(workflow, **context)

    # this is always called, even if an error occured in the workflow
    cleanup(**context)

    if res:
        requester.stdout.write('Done.\n')

# this implements walt image clone
def clone(requester, server, **kwargs):
    perform_clone(  requester = requester,
                    docker = server.docker,
                    image_store = server.images.store,
                    **kwargs)

