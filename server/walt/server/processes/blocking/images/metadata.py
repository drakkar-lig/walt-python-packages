from __future__ import annotations

import asyncio
import base64
import json

from walt.server.exttools import buildah
from walt.server.processes.blocking.registries import DockerHubClient
from walt.server.tools import async_gather_tasks


def collect_user_metadata(hub, user):
    return asyncio.run(async_collect_user_metadata(hub, user))


async def async_collect_user_metadata(hub, user):
    tasks = []
    async for repo in hub.async_list_user_repos(user):
        reponame = user + "/" + repo
        tasks += [asyncio.create_task(async_collect_repo_metadata(hub, reponame))]
    results = await async_gather_tasks(tasks)
    walt_images = {}
    for repo_images in results:
        walt_images.update(repo_images)
    return {"walt.user.images": walt_images}


async def async_collect_repo_metadata(hub, reponame):
    tasks, fullnames = [], []
    async for tag in hub.async_list_image_tags(reponame):
        fullname = reponame + ":" + tag
        task = asyncio.create_task(hub.async_get_labels(None, fullname))
        tasks.append(task)
        fullnames.append(fullname)
    results = await async_gather_tasks(tasks)
    walt_images = {}
    for fullname, labels in zip(fullnames, results):
        if "walt.node.models" in labels:
            walt_images[fullname] = dict(labels=labels)
    return walt_images


def push_user_metadata(requester, hub, user, metadata):
    encoded = base64.b64encode(json.dumps(metadata).encode("UTF-8"))
    encoded = encoded.decode("UTF-8")
    fullname = "%(user)s/walt_metadata:latest" % dict(user=user)
    cont_name = buildah("from", "scratch")
    # for the future (OCI images show only annotations in their manifest)
    buildah.config("--annotation", "metadata=" + encoded, cont_name)
    # for the present (legacy walt code parses only manifests with docker format)
    buildah.config("--label", "metadata=" + encoded, cont_name)
    # for now, save metadata images with docker manifest format
    buildah.commit("--format", "docker", cont_name, fullname)
    buildah.rm(cont_name)
    success = hub.push(requester, fullname)
    buildah.rmi(fullname)
    return success


def pull_user_metadata(hub, user):
    return asyncio.run(async_pull_user_metadata(hub, user))


async def async_pull_user_metadata(hub, user):
    try:
        labels = await hub.async_get_labels(
            None, "%(user)s/walt_metadata:latest" % dict(user=user)
        )
        encoded = labels["metadata"]
        return json.loads(base64.b64decode(encoded).decode("UTF-8"))
    except Exception:  # user did not push metadata yet
        return {"walt.user.images": {}}


def update_user_metadata_for_image(requester, hub, image_fullname, labels):
    hub_username = requester.get_registry_username("hub")
    # retrieve existing metadata (i.e. for other images...)
    metadata = pull_user_metadata(hub, hub_username)
    # update metadata of this image
    metadata["walt.user.images"][image_fullname] = dict(labels=labels)
    # push back on docker hub
    return push_user_metadata(requester, hub, hub_username, metadata)


def update_hub_metadata(requester, user):
    hub = DockerHubClient()
    # collect
    metadata = collect_user_metadata(hub, user)
    # push back on docker hub
    return push_user_metadata(requester, hub, user, metadata)
