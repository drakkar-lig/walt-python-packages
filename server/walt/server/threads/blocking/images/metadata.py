from __future__ import annotations

import typing

from walt.server.exttools import buildah
from walt.server.tools import async_gather_tasks
import json, base64
import asyncio

if typing.TYPE_CHECKING:
    from walt.server.threads.main.repositories import Repositories
    from walt.server.threads.main.server import Server


def collect_user_metadata(repositories: Repositories, user):
    return asyncio.run(async_collect_user_metadata(repositories, user))

async def async_collect_user_metadata(repositories: Repositories, user):
    tasks = []
    repos = await repositories.hub.async_list_user_repos(user)
    for repo in repos:
        reponame = user + '/' + repo
        tasks += [ asyncio.create_task(async_collect_repo_metadata(repositories, reponame)) ]
    results = await async_gather_tasks(tasks)
    walt_images = {}
    for repo_images in results:
        walt_images.update(repo_images)
    return { 'walt.user.images': walt_images }

async def async_collect_repo_metadata(repositories: Repositories, reponame):
    tags = await repositories.hub.async_list_image_tags(reponame)
    tasks, fullnames = [], []
    for tag in tags:
        fullname = reponame + ':' + tag
        task = asyncio.create_task(repositories.hub.async_get_labels(fullname))
        tasks.append(task)
        fullnames.append(fullname)
    results = await async_gather_tasks(tasks)
    walt_images = {}
    for fullname, labels in zip(fullnames, results):
        if 'walt.node.models' in labels:
            walt_images[fullname] = dict(
                labels = labels
            )
    return walt_images

def push_user_metadata(repositories: Repositories, dh_peer, auth_conf, requester, user, metadata):
    encoded = base64.b64encode(json.dumps(metadata).encode('UTF-8'))
    encoded = encoded.decode('UTF-8')
    fullname = '%(user)s/walt_metadata:latest' % dict(user = user)
    cont_name = buildah('from', 'scratch')
    # for the future (OCI images show only annotations in their manifest)
    buildah.config('--annotation', 'metadata=' + encoded, cont_name)
    # for the present (legacy walt code parses only manifests with docker format)
    buildah.config('--label', 'metadata=' + encoded, cont_name)
    # for now, save metadata images with docker manifest format
    buildah.commit('--format', 'docker', cont_name, fullname)
    buildah.rm(cont_name)
    repositories.hub.push(fullname, dh_peer, auth_conf, requester)
    buildah.rmi(fullname)

def pull_user_metadata(repositories: Repositories, user):
    return asyncio.run(async_pull_user_metadata(repositories, user))

async def async_pull_user_metadata(repositories: Repositories, user):
    try:
        labels = await repositories.hub.async_get_labels(
                '%(user)s/walt_metadata:latest' % dict(user = user))
        encoded = labels['metadata']
        return json.loads(base64.b64decode(encoded).decode('UTF-8'))
    except:     # user did not push metadata yet
        return { 'walt.user.images': {} }

def update_user_metadata_for_image(repositories: Repositories, image_store, dh_peer, auth_conf, \
                                   requester, image_fullname):
    user = image_fullname.split('/')[0]
    # read labels
    labels = image_store[image_fullname].labels
    # retrieve existing metadata (i.e. for other images...)
    metadata = pull_user_metadata(repositories, user)
    # update metadata of this image
    metadata['walt.user.images'][image_fullname] = dict(
        labels = labels
    )
    # push back on docker hub
    push_user_metadata(repositories, dh_peer, auth_conf, requester, user, metadata)

def update_hub_metadata(requester, server: Server, dh_peer, auth_conf, user):
    # collect
    metadata = collect_user_metadata(server.repositories, user)
    # push back on docker hub
    push_user_metadata(server.repositories, dh_peer, auth_conf, requester, user, metadata)
