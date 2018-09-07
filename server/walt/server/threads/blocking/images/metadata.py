#!/usr/bin/env python
import json, base64, subprocess
from io import BytesIO

USER_METADATA_DOCKERFILE = b'''\
FROM scratch
LABEL metadata='%(metadata)s'
'''

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
    encoded = base64.b64encode(json.dumps(metadata))
    content = USER_METADATA_DOCKERFILE % dict(metadata = encoded)
    dockerfile = BytesIO(content.encode('utf-8'))
    fullname = '%(user)s/walt_metadata:latest' % dict(user = user)
    docker.local.build(fileobj=dockerfile, rm=True, tag=fullname)
    docker.hub.push(fullname, dh_peer, auth_conf, requester)
    docker.local.rmi(fullname)

def pull_user_metadata(docker, user):
    try:
        labels = docker.hub.get_labels(
                '%(user)s/walt_metadata:latest' % dict(user = user))
        encoded = labels['metadata']
        return json.loads(base64.b64decode(encoded))
    except:     # user did not push metadata yet
        return { 'walt.user.images': {} }

def update_user_metadata_for_image(docker, dh_peer, auth_conf, \
                                   requester, image_fullname):
    user = image_fullname.split('/')[0]
    # read labels
    labels = docker.local.get_labels(image_fullname)
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
