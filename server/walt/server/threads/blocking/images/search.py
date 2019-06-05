import requests
from collections import defaultdict
from walt.server.tools import columnate, columnate_iterate_tty, \
                              format_node_models_list
from walt.server.threads.blocking.images.metadata import \
            pull_user_metadata

# About terminology: See comment about it in image.py.

SEARCH_HEADER = ['User', 'Image name', 'Location', 'Compatibility', 'Clonable link']
MSG_SEARCH_NO_MATCH = "Sorry, no image could match your request.\n"
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
    def __init__(self, docker, image_store, requester, validate = None):
        self.docker = docker
        self.image_store = image_store
        self.requester = requester
        if validate is None:
            def validate(user, name, location):
                return True
        self.validate = validate
    def validate_fullname(self, fullname, location):
        user, image_name = fullname.split('/')
        return self.validate(image_name, user, location)
    # search yields results in the form (<user>, <image_name>, <location>),
    # sorted by <user>, then <image_name>, and <location>.
    # since this can take time, we compute all results for one user,
    # then yield them for immediate display.
    def search(self):
        users = defaultdict(set)
        # search for local users
        for fullname in self.image_store:
            if self.validate_fullname(fullname, LOCATION_WALT_SERVER):
                users[fullname.split('/')[0]].add(LOCATION_WALT_SERVER)
        # search for hub users
        # (detect walt users by their 'walt_metadata' dummy image)
        for waltuser_info in self.docker.hub.search('walt_metadata'):
            if '/walt_metadata' in waltuser_info['name']:
                user = waltuser_info['name'].split('/')[0]
                users[user].add(LOCATION_DOCKER_HUB)
        # search images of each user
        for user in sorted(users):
            locations = users[user]
            images_and_labels = defaultdict(dict)
            # search on docker hub
            if LOCATION_DOCKER_HUB in locations:
                # read metadata to detect walt images of this user
                user_metadata = pull_user_metadata(self.docker, user)
                for fullname, info in user_metadata['walt.user.images'].items():
                    if self.validate_fullname(fullname, LOCATION_DOCKER_HUB):
                        image_name = fullname.split('/')[1]
                        images_and_labels[image_name][LOCATION_DOCKER_HUB] = info['labels']
            # search on local server
            if LOCATION_WALT_SERVER in locations:
                for fullname in self.image_store:
                    image_user, image_name = fullname.split('/')
                    if image_user != user:
                        continue
                    if self.validate_fullname(fullname, LOCATION_WALT_SERVER):
                        images_and_labels[image_name][LOCATION_WALT_SERVER] = \
                                            self.docker.local.get_labels(fullname)
            # yield results
            for image_name in sorted(images_and_labels):
                locations = sorted(images_and_labels[image_name])
                for location in locations:
                    labels = images_and_labels[image_name][location]
                    yield (user, image_name, location, labels)

def short_image_name(image_name):
    if image_name.endswith(':latest'):
        return image_name[:-7]
    else:
        return image_name

def clonable_link(location, user, image_name):
    return "%s:%s/%s" % (
            LOCATION_LABEL[location],
            user,
            short_image_name(image_name)
    )

def discard_images_in_ws(it, username):
    # images owned by the requester and present locally on
    # the server are not considered "remote images".
    # (they belong to the working set of the user, instead.)
    for user, image_name, location, labels in it:
        if user != username or location == LOCATION_DOCKER_HUB:
            yield user, image_name, location, labels

def format_result(it):
    for user, image_name, location, labels in it:
        node_models = labels['walt.node.models'].split(',')
        yield ( user,
                short_image_name(image_name),
                LOCATION_LONG_LABEL[location],
                format_node_models_list(node_models),
                clonable_link(location, user, image_name))

# this implements walt image search
def perform_search(docker, image_store, requester, keyword, tty_mode):
    username = requester.get_username()
    if not username:
        return None    # client already disconnected, give up
    if keyword:
        def validate(image_name, user, location):
            return keyword in clonable_link(location, user, image_name)
    else:
        validate = None
    # search
    search = Search(docker, image_store, requester, validate)
    it = search.search()
    it = discard_images_in_ws(it, username)
    it = format_result(it)

    found = False
    if tty_mode:
        # allow escape-codes to reprint lines, if a new row has columns
        # with a size larger than previous ones.
        for s in columnate_iterate_tty(it, SEARCH_HEADER):
            found = True
            requester.stdout.write(s)
    else:
        # wait for all results to be available, in order to compute
        # the appropriate column formatting.
        s = columnate(it, SEARCH_HEADER)
        if len(s) > 0:
            found = True
            requester.stdout.write(s + '\n')
    if not found:
        requester.stderr.write(MSG_SEARCH_NO_MATCH)

# this implements walt image search
def search(requester, server, keyword, tty_mode):
    return perform_search(server.docker, server.images.store, requester, keyword, tty_mode)

