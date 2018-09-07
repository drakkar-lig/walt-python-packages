import requests
from collections import defaultdict
from walt.server.tools import columnate

# About terminology: See comment about it in image.py.

LOCATION_WALT_SERVER = 0
LOCATION_DOCKER_HUB = 1
LOCATION_LABEL = {
    LOCATION_WALT_SERVER: 'server',
    LOCATION_DOCKER_HUB: 'hub',
}
LOCATION_LONG_LABEL = {
    LOCATION_WALT_SERVER: 'WalT server',
    LOCATION_DOCKER_HUB: 'docker hub',
}

LOCATION_PER_LABEL = {v: k for k, v in LOCATION_LABEL.items()}

class Search(object):
    def __init__(self, docker, requester):
        self.docker = docker
        self.requester = requester
        self.result = defaultdict(lambda : defaultdict(set))
    # search returns a dictionary with the following format:
    # { <tag> -> { <user> -> <location> } }
    def search(self, validate = None):
        candidates = []
        if not validate:
            def validate(user, tag, location):
                return True
        # look up for candidates on the docker hub
        for result in self.hub.docker.search('walt'):
            if '/walt-node' in result['name']:
                for tag in self.docker.hub.list_image_tags(result['name']):
                    user = result['name'].split('/')[0]
                    candidates.append((user, tag, LOCATION_DOCKER_HUB))
        # look up for candidates locally on the server
        for fullname in self.docker.local.get_images():
            if '/walt-node' in fullname:
                user, tag = fullname.split('/walt-node:')
                candidates.append((user, tag, LOCATION_WALT_SERVER))
        # validate candidates
        for user, tag, location in candidates:
            if validate(user, tag, location):
                self.insert_result(tag, user, location)
        return self.result
    def insert_result(self, tag, user, location):
        self.result[tag][user].add(location)

# this implements walt image search
def perform_search(docker, requester, keyword):
    username = requester.get_username()
    if not username:
        return None    # client already disconnected, give up
    # images owned by the requester and present locally on
    # the server are not considered "remote images".
    # (they belong to the working set of the user, instead.)
    def validate_not_in_ws(user, tag, location):
        return user != username or \
                location == LOCATION_DOCKER_HUB
    if keyword:
        def validate(user, tag, location):
            if not validate_not_in_ws(user, tag, location):
                return False
            remote_name = "%s:%s/%s" % ( \
                    LOCATION_LABEL[location], user, tag)
            return keyword in remote_name
    else:
        validate = validate_not_in_ws
    # search
    result = Search(docker, requester).search(validate)
    # print
    records = []
    for tag in result:
        for user in result[tag]:
            for location in result[tag][user]:
                clonable_link = "%s:%s/%s" % (\
                    LOCATION_LABEL[location],
                    user,
                    tag
                )
                records.append([
                    user, tag, LOCATION_LONG_LABEL[location], clonable_link
                ])
    return columnate(sorted(records), \
               ['User', 'Image name', 'Location', 'Clonable link'])

# this implements walt image search
def search(requester, server, keyword):
    return perform_search(server.docker, requester, keyword)

