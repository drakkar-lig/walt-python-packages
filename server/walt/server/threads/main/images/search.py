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
        for result in self.docker.search('walt-node'):
            if '/walt-node' in result['name']:
                for user, tag in self.docker.lookup_remote_tags(result['name']):
                    candidates.append((user, tag, LOCATION_DOCKER_HUB))
        # look up for candidates locally on the server
        for fullname in self.docker.get_local_images():
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

class SearchTask(object):
    def __init__(self, hub_task, docker, requester, keyword):
        self.hub_task = hub_task
        self.docker = docker
        self.requester = requester
        self.keyword = keyword
    def perform(self):
        return perform_search(self.docker, self.requester, self.keyword)
    def handle_result(self, res):
        if isinstance(res, requests.exceptions.RequestException):
            res = 'Network connection to docker hub failed.'
        self.hub_task.return_result(res)

# this implements walt image search
def search(hub_task, blocking_manager, docker, requester, keyword):
    # the result of the task the hub thread submitted to us
    # will not be available right now
    hub_task.set_async()
    blocking_manager.do(SearchTask(hub_task, docker, requester, keyword))


