#!/usr/bin/env python
from walt.server.exttools import buildah
import json, base64

def collect_user_metadata(docker, user):
    walt_images = {}
    for repo in docker.hub.list_user_repos(user):
        reponame = user + '/' + repo
        for tag in docker.hub.list_image_tags(reponame):
            fullname = reponame + ':' + tag
            labels = docker.hub.get_labels(fullname)
            if 'walt.node.models' in labels:
                walt_images[fullname] = dict(
                    labels = labels
                )
    return { 'walt.user.images': walt_images }

def push_user_metadata(docker, dh_peer, auth_conf, requester, user, metadata):
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
    docker.hub.push(fullname, dh_peer, auth_conf, requester)
    buildah.rmi(fullname)

def pull_user_metadata(docker, user):
    try:
        labels = docker.hub.get_labels(
                '%(user)s/walt_metadata:latest' % dict(user = user))
        encoded = labels['metadata']
        return json.loads(base64.b64decode(encoded).decode('UTF-8'))
    except:     # user did not push metadata yet
        return { 'walt.user.images': {} }

def update_user_metadata_for_image(docker, image_store, dh_peer, auth_conf, \
                                   requester, image_fullname):
    user = image_fullname.split('/')[0]
    # read labels
    labels = image_store[image_fullname].labels
    # retrieve existing metadata (i.e. for other images...)
    metadata = pull_user_metadata(docker, user)
    # update metadata of this image
    metadata['walt.user.images'][image_fullname] = dict(
        labels = labels
    )
    # push back on docker hub
    push_user_metadata(docker, dh_peer, auth_conf, requester, user, metadata)

def update_hub_metadata(requester, server, dh_peer, auth_conf, user):
    # collect
    metadata = collect_user_metadata(server.docker, user)
    # push back on docker hub
    push_user_metadata(server.docker, dh_peer, auth_conf, requester, user, metadata)
