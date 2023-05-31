from __future__ import annotations

import re
import subprocess
import typing
import uuid

from walt.common.formatting import format_sentence
from walt.server.exttools import docker
from walt.server.processes.blocking.images.metadata import pull_user_metadata
from walt.server.processes.blocking.registries import (
    DockerDaemonClient,
    DockerHubClient,
    get_custom_registry_client,
)
from walt.server.tools import get_clone_url_locations

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server

# About terminology: See comment about it in image.py.

# Implementation notes:
# walt image clone relies on a complex process.
# depending on what we are cloning, who we are,
# what are the existing images and whether
# we want to overwrite these existing images or not,
# we have many cases to think about.
# that's why we have organised this process as follows:
# 1- we search for existing images
# 2- we perform basic validation of the request
# 3- we compute a workflow (a list of function calls)
# 4- we execute this workflow.
#
# (also note that since docker-hub downloads may take a long time,
# we also have to implement this in an asynchronous task.)

MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS = """\
Invalid clonable image link.
Images of the form 'walt:%s/<image_name>' already belong to
your working set and thus are not clonable.
"""
MSG_USE_FORCE_CLI = """\
If this is what you want, rerun with --force:
$ %s
"""
MSG_USE_FORCE_API = """\
If this is what you want, use force=True.
"""
MSG_INVALID_CLONABLE_LINK = """\
Invalid clonable image link. Format must be:
{link_format}
(tip: walt image search [<keyword>])
"""
MSG_INCOMPATIBLE_MODELS = """\
Sorry, cannot proceed. There is an image with the same name in your
working set. Overriding it is not allowed because it is currently
in use, and the target image is not compatible with %s.
"""


# Subroutines
# -----------
def fix_image_name(requester, image_name):
    new_name = re.sub("[^a-z0-9:]+", "-", image_name.lower())
    if new_name != image_name:
        requester.stdout.write(
            f'Image will be recorded as "{new_name}" since original name is not valid'
            " in WALT.\n"
        )
    return new_name


def parse_clonable_link(requester, clonable_link):
    bad = False
    parts = clonable_link.split(":", 1)
    if len(parts) != 2:
        bad = True
    if not bad:
        location = parts[0]
        if location not in get_clone_url_locations():
            bad = True
    if not bad:
        parts = parts[1].split("/")
        if len(parts) != 2:
            bad = True
    if not bad:
        user, image_name = parts
        parts = image_name.split(":")
        if len(parts) == 1:
            image_name += ":latest"
        elif len(parts) != 2:
            bad = True
    if not bad:
        return (location, user, image_name)
    if bad:
        locations_or = "|".join(get_clone_url_locations())
        link_format = f"[{locations_or}]:<user>/<image_name>[:<tag>]"
        requester.stderr.write(
            MSG_INVALID_CLONABLE_LINK.format(link_format=link_format)
        )
        return None, None, None


def get_temp_image_fullname():
    return "walt/clone-temp:" + str(uuid.uuid4()).split("-")[0]


def exit_no_such_image(requester):
    requester.stderr.write("No such remote image. Use walt image search <keyword>.\n")
    return ("FAILED",)


def exit_image_without_models(requester):
    requester.stderr.write(
        "Failed. This remote image does not indicate compatible node models.\n"
    )
    return ("FAILED",)


# workflow functions
# ------------------


# Note: we save initial images, because:
# * in some cases we want to retain the filesystem layers otherwise we
# would need to download them again (case of the overwrite of a server
# image with its updated hub version)
# * if we detect an issue late in the workflow, we can still restore them.
def save_initial_images(
    saved_images,
    ws_image_fullname,
    remote_image_fullname,
    existing_server_image,
    existing_ws_image,
    walt_local_repo,
    **args,
):
    initial_image_fullnames = set()
    for fullname, exists in (
        (ws_image_fullname, existing_ws_image),
        (remote_image_fullname, existing_server_image),
    ):
        if exists:
            initial_image_fullnames.add(fullname)
    for image_fullname in initial_image_fullnames:
        image_backup = get_temp_image_fullname()
        walt_local_repo.tag(image_fullname, image_backup)
        saved_images[image_fullname] = image_backup


def error_image_belongs_to_ws(requester, username, **args):
    requester.stderr.write(MSG_IMAGE_NOT_REMOTE_BELONGS_TO_WS % username)
    return False


def verify_overwrite(
    image_store, requester, clonable_link, ws_image_fullname, force, image_name, **args
):
    if not force:
        client_type = requester.get_client_type()
        if client_type is None:
            return False  # already disconnected
        msg = image_store.get_image_overwrite_warning(ws_image_fullname)
        if client_type == "cli":
            force_clone = "walt image clone --force " + clonable_link
            if image_name is not None and not clonable_link.endswith(image_name):
                force_clone += " " + image_name
            msg += MSG_USE_FORCE_CLI % force_clone
        elif client_type == "api":
            msg += MSG_USE_FORCE_API
        requester.stderr.write(msg)
        return False


# check possible compatibility issue regarding node models
def verify_compatibility_issue(
    image_store, requester, ws_image_fullname, target_node_models, nodes_manager, **args
):
    ws_image = image_store[ws_image_fullname]
    if not ws_image.in_use():
        return  # no problem
    # there is a risk of overwritting the mounted ws image with
    # a target image that is incompatible.
    needed_models = nodes_manager.get_node_models_using_image(ws_image_fullname)
    image_compatible_models = set(target_node_models)
    incompatible_models = needed_models - image_compatible_models
    if len(incompatible_models) > 0:
        sentence = format_sentence(
            MSG_INCOMPATIBLE_MODELS,
            incompatible_models,
            None,
            "node model",
            "node models",
        )
        requester.stderr.write(sentence)
        return False  # give up


def remove_ws_image(image_store, walt_local_repo, ws_image_fullname, **args):
    ws_image = image_store[ws_image_fullname]
    ws_image.filesystem.close()
    walt_local_repo.untag(ws_image_fullname)


def remove_server_image(walt_local_repo, remote_image_fullname, **args):
    walt_local_repo.untag(remote_image_fullname)


def restore_initial_ws_image(walt_local_repo, ws_image_fullname, saved_images, **args):
    ws_image_backup = saved_images[ws_image_fullname]
    walt_local_repo.tag(ws_image_backup, ws_image_fullname)


def restore_initial_server_image(
    walt_local_repo, remote_image_fullname, saved_images, **args
):
    server_image_backup = saved_images[remote_image_fullname]
    walt_local_repo.tag(server_image_backup, remote_image_fullname)


def tag_server_image_to_requester(
    walt_local_repo, ws_image_fullname, remote_image_fullname, **args
):
    walt_local_repo.tag(remote_image_fullname, ws_image_fullname)


def pull_image(requester, server, remote_location, remote_image_fullname, **args):
    if remote_location == "hub":
        hub = DockerHubClient()
        hub.pull(requester, server, remote_image_fullname)
    elif remote_location == "docker":
        docker_daemon = DockerDaemonClient()
        docker_daemon.pull(requester, server, remote_image_fullname)
    else:
        registry = get_custom_registry_client(remote_location)
        registry.pull(requester, server, remote_image_fullname)


class WorkflowCleaner:
    def __init__(self, context):
        self.context = context

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:  # ok, no exception
            self.cleanup(True, **self.context)
        else:  # not ok, an exception occured!
            self.cleanup(False, **self.context)

    def cleanup(
        self,
        ok,
        walt_local_repo,
        image_store,
        saved_images,
        ws_image_fullname,
        remote_image_fullname,
        **args,
    ):
        if not ok:  # only if an exception occured
            # remove any temporary images created there
            walt_local_repo.untag(ws_image_fullname, ignore_missing=True)
            walt_local_repo.untag(remote_image_fullname, ignore_missing=True)
            # restore the backups
            for image_fullname, backup_fullname in saved_images.items():
                walt_local_repo.tag(backup_fullname, image_fullname)
        # in any case cleanup the backup tags
        for backup_fullname in saved_images.values():
            walt_local_repo.untag(backup_fullname)
        # if ok, update the image store
        # (otherwise we just restored things from backup, so there was no change)
        if ok:
            image_store.resync_from_registry()
            image_store.trigger_update_image_mounts()


# workflow management functions
# -----------------------------
def workflow_exit(**context):
    return False


def workflow_if(condition_func, workflow_if_true, workflow_if_false):
    def workflow_if_instance(**context):
        if condition_func(**context) is not False:
            return workflow_run(workflow_if_true, **context)
        else:
            return workflow_run(workflow_if_false, **context)

    return workflow_if_instance


def workflow_run(workflow, **context):
    for f in workflow:
        res = f(**context)
        if res is False:
            return False  # issue, stop here
    return True


# walt image clone implementation
# -------------------------------
def perform_clone(requester, clonable_link, image_store, force, image_name, **kwargs):
    username = requester.get_username()
    if not username:
        return ("FAILED",)  # client already disconnected, give up
    remote_location, remote_user, remote_image_name = parse_clonable_link(
        requester, clonable_link
    )
    if remote_location is None:
        return ("FAILED",)  # error already reported

    if image_name is None:
        # if not specified, name it the same as remote image
        image_name = fix_image_name(requester, remote_image_name)

    ws_image_fullname = "%s/%s" % (username, image_name)
    if ":" not in image_name:
        ws_image_fullname += ":latest"
    remote_image_fullname = "%s/%s" % (remote_user, remote_image_name)

    # analyse our context
    existing_server_image = image_store.__contains__(remote_image_fullname)
    existing_ws_image = image_store.__contains__(ws_image_fullname)
    same_image = remote_image_fullname == ws_image_fullname
    image_is_local = remote_location == "walt"

    # check that the requested image really exists,
    # and fetch compatibility info
    if remote_location == "walt":
        if not image_store.__contains__(remote_image_fullname):
            return exit_no_such_image(requester)
        labels = image_store[remote_image_fullname].get_labels()
    elif remote_location == "hub":
        hub = DockerHubClient()
        remote_user_metadata = pull_user_metadata(hub, remote_user)
        if remote_image_fullname not in remote_user_metadata["walt.user.images"]:
            return exit_no_such_image(requester)
        image_info = remote_user_metadata["walt.user.images"][remote_image_fullname]
        labels = image_info["labels"]
    elif remote_location == "docker":
        if docker is None:
            requester.stderr.write("Docker is not available on the server.\n")
            return ("FAILED",)
        try:
            docker_daemon = DockerDaemonClient()
            labels = docker_daemon.get_labels(requester, remote_image_fullname)
        except subprocess.CalledProcessError:
            requester.stderr.write("Error while loading images from Docker.\n")
            return ("FAILED",)
    else:
        registry = get_custom_registry_client(remote_location)
        try:
            labels = registry.get_labels(requester, remote_image_fullname)
        except Exception:
            return exit_no_such_image(requester)
    if "walt.node.models" not in labels:
        return exit_image_without_models(requester)
    target_node_models = labels["walt.node.models"].split(",")

    # compute the workflow
    # --------------------
    # obvious facts:
    # * if image_is_local is True, existing_server_image is True
    # * if same_image is True, existing_server_image == existing_ws_image
    # that's why not all workflow entries are possible.
    workflow_selector = {
        # image_is_local, existing_server_image, existing_ws_image, same_image
        (True, True, False, False): [tag_server_image_to_requester],
        (True, True, True, False): [
            verify_compatibility_issue,
            verify_overwrite,
            remove_ws_image,
            tag_server_image_to_requester,
        ],
        (True, True, True, True): [error_image_belongs_to_ws],
        (False, False, False, False): [
            pull_image,
            tag_server_image_to_requester,
            remove_server_image,
        ],
        (False, False, True, False): [
            verify_compatibility_issue,
            verify_overwrite,
            pull_image,
            remove_ws_image,
            tag_server_image_to_requester,
            remove_server_image,
        ],
        (False, True, False, False): [
            remove_server_image,
            pull_image,
            tag_server_image_to_requester,
            remove_server_image,
            restore_initial_server_image,
        ],
        (False, True, True, False): [
            verify_compatibility_issue,
            verify_overwrite,
            remove_server_image,
            pull_image,
            remove_ws_image,
            tag_server_image_to_requester,
            remove_server_image,
            restore_initial_server_image,
        ],
        (False, False, False, True): [pull_image],
        (False, True, True, True): [
            verify_compatibility_issue,
            verify_overwrite,
            remove_ws_image,
            pull_image,
        ],
    }
    workflow = [save_initial_images]  # this is always called first
    workflow += workflow_selector[
        (image_is_local, existing_server_image, existing_ws_image, same_image)
    ]
    print("clone workflow is:", ", ".join([f.__name__ for f in workflow]))

    # proceed
    # -------
    context = dict(
        image_name=image_name,
        remote_location=remote_location,
        username=username,
        ws_image_fullname=ws_image_fullname,
        remote_image_fullname=remote_image_fullname,
        existing_server_image=existing_server_image,
        existing_ws_image=existing_ws_image,
        image_store=image_store,
        requester=requester,
        force=force,
        saved_images={},
        clonable_link=clonable_link,
        target_node_models=target_node_models,
        **kwargs,
    )

    # we use a context manager ("with-construct") to ensure
    # the WorkflowCleaner.cleanup function will be called,
    # even in case of an exception.
    # this fonction will remove any temporary image.
    res = False
    with WorkflowCleaner(context):
        res = workflow_run(workflow, **context)

    if res:
        if existing_ws_image:
            return ("OK_BUT_REBOOT_NODES", ws_image_fullname)
        else:
            return ("OK", ws_image_fullname)
    else:
        return ("FAILED",)


# this implements walt image clone
def clone(requester, server: Server, **kwargs):
    try:
        return perform_clone(
            requester=requester,
            server=server,
            walt_local_repo=server.registry,
            image_store=server.images.store,
            nodes_manager=server.nodes,
            **kwargs,
        )
    except Exception as e:
        requester.stderr.write(str(e) + "\n")
        return ("FAILED",)
