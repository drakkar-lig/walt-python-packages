import requests
from walt.server import const
from walt.server.tools import columnate, \
                display_transient_label, hide_transient_label

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
    def __init__(self, c, requester, transient_label='Searching...'):
        self.c = c
        self.requester = requester
        self.result = {}
        self.transient_label = transient_label
    def lookup_remote_tags(self, image_name):
        url = const.DOCKER_HUB_GET_TAGS_URL % dict(image_name = image_name)
        r = requests.get(url)
        for elem in requests.get(url).json():
            tag = requests.utils.unquote(elem['name'])
            yield (image_name.split('/')[0], tag)
    # search returns a dictionary with the following format:
    # { <tag> -> { <user> -> <location> } }
    def search(self, validate = None):
        display_transient_label(self.requester.stdout, self.transient_label)
        candidates = []
        if not validate:
            def validate(user, tag, location):
                return True
        # look up for candidates on the docker hub
        for result in self.c.search(term='walt-node'):
            if '/walt-node' in result['name']:
                for user, tag in self.lookup_remote_tags(result['name']):
                    candidates.append((user, tag, LOCATION_DOCKER_HUB))
        # look up for candidates locally on the server
        for fullname in sum([ i['RepoTags'] for i in self.c.images() ], []):
            if '/walt-node' in fullname:
                user, tag = fullname.split('/walt-node:')
                candidates.append((user, tag, LOCATION_WALT_SERVER))
        # validate candidates
        for user, tag, location in candidates:
            if validate(user, tag, location):
                self.insert_result(tag, user, location)
        hide_transient_label(self.requester.stdout, self.transient_label)
        return self.result
    def insert_result(self, tag, user, location):
        if tag not in self.result:
            self.result[tag] = {}
        if user not in self.result[tag]:
            self.result[tag][user] = set([])
        self.result[tag][user].add(location)

# this implements walt image search
def perform_search(c, requester, keyword):
    # images owned by the requester and present locally on
    # the server are not considered "remote images".
    # (they belong to the working set of the user, instead.)
    def validate_not_in_ws(user, tag, location):
        return user != requester.username or \
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
    result = Search(c, requester).search(validate)
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
    def __init__(self, q, c, requester, keyword):
        self.response_q = q
        self.docker = c
        self.requester = requester
        self.keyword = keyword
    def perform(self):
        return perform_search(self.docker, self.requester, self.keyword)
    def handle_result(self, res):
        self.response_q.put(res)

# this implements walt image search
def search(q, blocking_manager, c, requester, keyword):
    blocking_manager.do(SearchTask(q, c, requester, keyword))


