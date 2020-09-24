import requests, uuid
from walt.server.threads.blocking.images.search import \
        LOCATION_WALT_SERVER, LOCATION_DOCKER_HUB, LOCATION_DOCKER_DAEMON, \
        LOCATION_LABEL, LOCATION_PER_LABEL
from walt.server.threads.blocking.images.metadata import \
            pull_user_metadata
from walt.common.tools import format_sentence

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
Images of the form 'walt:%s/<image_name>' already belong to
your working set and thus are not clonable.
"""
MSG_USE_FORCE = """\
If this is what you want, rerun with --force:
$ %s
"""
MSG_INVALID_CLONABLE_LINK = """\
Invalid clonable image link. Format must be:
[walt|docker|hub]:<user>/<image_name>[:<tag>]
(tip: walt image search [<keyword>])
"""
MSG_INCOMPATIBLE_MODELS = """\
Sorry, cannot proceed. There is an image with the same name in your
working set. Overriding it is not allowed because it is currently
in use, and the target image is not compatible with %s.
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

def exit_no_such_image(requester):
    requester.stderr.write(
            'No such remote image. Use walt image search <keyword>.\n')
    return ('FAILED',)

# workflow functions
# ------------------

# Note: we save initial images, because:
# * in some cases we want to retain the filesystem layers otherwise we
# would need to download them again (case of the overwrite of a server
# image with its updated hub version)
# * if we detect an issue late in the workflow, we can still restore them.
def save_initial_images(saved_images,
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

def error_image_belongs_to_ws(requester, username, **args):
    requester.stderr.write(
        MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS % username)
    return False

def verify_overwrite(image_store, requester, clonable_link,
                    ws_image_fullname, force, image_name, **args):
    if not force:
        image_store.warn_overwrite_image(requester, ws_image_fullname)
        force_clone = "walt image clone --force " + clonable_link
        if image_name is not None:
            force_clone += ' ' + image_name
        requester.stderr.write(MSG_USE_FORCE % force_clone)
        return False

# check possible compatibility issue regarding node models
def verify_compatibility_issue(image_store, requester, clonable_link,
                    ws_image_fullname, remote_image_fullname,
                    docker, target_node_models, nodes_manager, **args):
    ws_image = image_store[ws_image_fullname]
    if not ws_image.in_use:
        return  # no problem
    # there is a risk of overwritting the mounted ws image with
    # a target image that is incompatible.
    nodes = nodes_manager.get_nodes_using_image(ws_image_fullname)
    needed_models = set(node.model for node in nodes)
    image_compatible_models = set(target_node_models)
    incompatible_models = needed_models - image_compatible_models
    if len(incompatible_models) > 0:
        sentence = format_sentence(MSG_INCOMPATIBLE_MODELS, incompatible_models,
                        None, 'node model', 'node models')
        requester.stderr.write(sentence)
        return False    # give up

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

def pull_image(docker, requester, remote_location, remote_image_fullname, **args):
    if remote_location == LOCATION_DOCKER_HUB:
        docker.hub.pull(remote_image_fullname, requester)
    elif remote_location == LOCATION_DOCKER_DAEMON:
        docker.daemon.pull(remote_image_fullname, requester)

class WorkflowCleaner:
    def __init__(self, context):
        self.context = context
    def __enter__(self):
        pass
    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:    # ok, no exception
            self.cleanup(True, **self.context)
        else:                   # not ok, an exception occured!
            self.cleanup(False, **self.context)
    def cleanup(self, ok, docker, image_store, saved_images,
                ws_image_fullname, remote_image_fullname,
                existing_server_image, existing_ws_image, **args):
        if not ok:  # only if an exception occured
            # remove any temporary images created there
            docker.local.untag(ws_image_fullname, ignore_missing=True)
            docker.local.untag(remote_image_fullname, ignore_missing=True)
            # restore the backups
            for image_fullname, backup_fullname in saved_images.items():
                docker.local.tag(backup_fullname, image_fullname)
        # if ok, update the image store
        # (otherwise we just restored things from backup, so there was no change)
        if ok:
            docker.local.clear_name_cache()
            image_store.refresh()
            image_store.update_image_mounts()
        # in any case cleanup the backup tags
        for backup_fullname in saved_images.values():
            docker.local.untag(backup_fullname)

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
    return True

# walt image clone implementation
# -------------------------------
def perform_clone(requester, docker, nodes_manager, clonable_link, image_store, force, image_name):
    username = requester.get_username()
    if not username:
        return ('FAILED',) # client already disconnected, give up
    remote_location, remote_user, remote_image_name = parse_clonable_link(
                                                requester, clonable_link)
    if remote_location == None:
        return ('FAILED',) # error already reported

    if image_name is None:
        # if not specified, name it the same as remote image
        ws_image_fullname = "%s/%s" % (username, remote_image_name)
    else:
        ws_image_fullname = "%s/%s" % (username, image_name)
        if ':' not in image_name:
            ws_image_fullname += ':latest'
    remote_image_fullname = "%s/%s" % (remote_user, remote_image_name)

    # analyse our context
    existing_server_image = remote_image_fullname in image_store
    existing_ws_image = ws_image_fullname in image_store
    same_image = (remote_image_fullname == ws_image_fullname)
    image_is_local = (remote_location == LOCATION_WALT_SERVER)

    # check that the requested image really exists,
    # and fetch compatibility info
    if remote_location == LOCATION_WALT_SERVER:
        if remote_image_fullname not in image_store:
            return exit_no_such_image(requester)
        target_node_models = image_store[remote_image_fullname].get_node_models()
    if remote_location == LOCATION_DOCKER_HUB:
        remote_user_metadata = pull_user_metadata(docker, remote_user)
        if remote_image_fullname not in remote_user_metadata['walt.user.images']:
            return exit_no_such_image(requester)
        image_info = remote_user_metadata['walt.user.images'][remote_image_fullname]
        target_node_models = image_info['labels']['walt.node.models'].split(',')
    if remote_location == LOCATION_DOCKER_DAEMON:
        labels = None
        try:
            labels = docker.daemon.get_labels(remote_image_fullname)
        except:
            return exit_no_such_image(requester)
        target_node_models = labels['walt.node.models'].split(',')

    # compute the workflow
    # --------------------
    # obvious facts:
    # * if image_is_local is True, existing_server_image is True
    # * if same_image is True, existing_server_image == existing_ws_image
    # that's why not all workflow entries are possible.
    workflow_selector = {
        # image_is_local, existing_server_image, existing_ws_image, same_image
        (True, True, False, False): [ tag_server_image_to_requester ],
        (True, True, True, False):  [ verify_compatibility_issue, verify_overwrite,
                                                        remove_ws_image, tag_server_image_to_requester ],
        (True, True, True, True):   [ error_image_belongs_to_ws ],

        (False, False, False, False): [ pull_image, tag_server_image_to_requester, remove_server_image ],
        (False, False, True, False):  [ verify_compatibility_issue, verify_overwrite, pull_image,
                                                        remove_ws_image, \
                                                        tag_server_image_to_requester, remove_server_image ],
        (False, True, False, False):  [ remove_server_image, pull_image,
                                                        tag_server_image_to_requester, remove_server_image,
                                                        restore_initial_server_image ],
        (False, True, True, False):   [ verify_compatibility_issue, verify_overwrite,
                                                        remove_server_image, pull_image,
                                                        remove_ws_image, tag_server_image_to_requester,
                                                        remove_server_image, restore_initial_server_image ],
        (False, False, False, True):  [ pull_image ],
        (False, True, True, True):    [ verify_compatibility_issue, verify_overwrite, remove_ws_image,
                                                        pull_image ],
    }
    workflow = [ save_initial_images ]     # this is always called first
    workflow += workflow_selector[(image_is_local, existing_server_image, existing_ws_image, same_image)]
    print('clone workflow is:', ', '.join([ f.__name__ for f in workflow ]))

    # proceed
    # -------
    context = dict(
        image_name = image_name,
        remote_location = remote_location,
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
        clonable_link = clonable_link,
        target_node_models = target_node_models,
        nodes_manager = nodes_manager
    )

    # we use a context manager ("with-construct") to ensure
    # the WorkflowCleaner.cleanup function will be called,
    # even in case of an exception.
    # this fonction will remove any temporary docker image.
    res = False
    with WorkflowCleaner(context):
        res = workflow_run(workflow, **context)

    if res:
        requester.stdout.write('Done.\n')
        if existing_ws_image:
            return ('OK_BUT_REBOOT_NODES', ws_image_fullname)
        else:
            return ('OK',)
    else:
        return ('FAILED',)

# this implements walt image clone
def clone(requester, server, **kwargs):
    return perform_clone(  requester = requester,
                    docker = server.docker,
                    image_store = server.images.store,
                    nodes_manager = server.nodes,
                    **kwargs)

