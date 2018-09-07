import requests
from collections import defaultdict
from walt.server.tools import columnate
from walt.server.threads.blocking.images.metadata import \
            pull_user_metadata

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

# in order to efficiently search for walt images on the docker hub,
# each walt user has a dummy image called 'walt_metadata' pushed on
# its docker hub account. This image is refreshed each time an image
# is published with "walt image publish".

class Search(object):
    def __init__(self, docker, image_store, requester):
        self.docker = docker
        self.image_store = image_store
        self.requester = requester
        self.result = defaultdict(lambda : defaultdict(set))
    # search returns a dictionary with the following format:
    # { <image_name> -> { <user> -> <location> } }
    def search(self, validate = None):
        candidates = []
        if not validate:
            def validate(user, name, location):
                return True
        # look up for candidates remotely on the hub
        # detect walt users by their 'walt_metadata' dummy image
        for waltuser_info in self.docker.hub.search('walt_metadata'):
            if '/walt_metadata' in waltuser_info['name']:
                user = waltuser_info['name'].split('/')[0]
                # read metadata to detect walt images of this user
                user_metadata = pull_user_metadata(self.docker, user)
                for fullname, info in user_metadata['walt.user.images'].items():
                    user, image_name = fullname.split('/')
                    candidates.append((image_name, user, LOCATION_DOCKER_HUB))
        # look up for candidates locally on the server
        for fullname in self.image_store:
            user, image_name = fullname.split('/')
            candidates.append((image_name, user, LOCATION_WALT_SERVER))
        # validate candidates
        for candidate_info in candidates:
            if validate(*candidate_info):
                self.insert_result(*candidate_info)
        return self.result
    def insert_result(self, image_name, user, location):
        self.result[image_name][user].add(location)

# this implements walt image search
def perform_search(docker, image_store, requester, keyword):
    username = requester.get_username()
    if not username:
        return None    # client already disconnected, give up
    # images owned by the requester and present locally on
    # the server are not considered "remote images".
    # (they belong to the working set of the user, instead.)
    def validate_not_in_ws(image_name, user, location):
        return user != username or \
                location == LOCATION_DOCKER_HUB
    if keyword:
        def validate(image_name, user, location):
            if not validate_not_in_ws(image_name, user, location):
                return False
            remote_name = "%s:%s/%s" % ( \
                    LOCATION_LABEL[location], user, image_name)
            return keyword in remote_name
    else:
        validate = validate_not_in_ws
    # search
    result = Search(docker, image_store, requester).search(validate)
    # print
    records = []
    for image_name in result:
        if image_name.endswith(':latest'):
            short_image_name = image_name[:-7]
        else:
            short_image_name = image_name
        for user in result[image_name]:
            for location in result[image_name][user]:
                clonable_link = "%s:%s/%s" % (\
                    LOCATION_LABEL[location],
                    user,
                    short_image_name
                )
                records.append([
                    user, short_image_name, LOCATION_LONG_LABEL[location], clonable_link
                ])
    return columnate(sorted(records), \
               ['User', 'Image name', 'Location', 'Clonable link'])

# this implements walt image search
def search(requester, server, keyword):
    return perform_search(server.docker, server.images.store, requester, keyword)

