import requests
from collections import defaultdict
from walt.server.tools import columnate, columnate_iterate_tty, \
                              format_node_models_list
from walt.server.threads.blocking.images.metadata import \
            pull_user_metadata
from walt.common.version import __version__

# About terminology: See comment about it in image.py.

SEARCH_HEADER = ['User', 'Image name', 'Location', 'Compatibility', 'Clonable link']
MSG_SEARCH_NO_MATCH = "Sorry, no image could match your request.\n"
LOCATION_WALT_SERVER = 0
LOCATION_DOCKER_HUB = 1
LOCATION_DOCKER_DAEMON = 2
LOCATION_LABEL = {
    LOCATION_WALT_SERVER: 'walt',
    LOCATION_DOCKER_HUB: 'hub',
    LOCATION_DOCKER_DAEMON: 'docker',
}
LOCATION_LONG_LABEL = {
    LOCATION_WALT_SERVER: 'walt (other user)',
    LOCATION_DOCKER_HUB: 'docker hub',
    LOCATION_DOCKER_DAEMON: 'docker daemon'
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
        parts = fullname.split('/')
        if len(parts) != 2:
            return False
        user, image_name = parts
        return self.validate(image_name, user, location)
    # search yields results in the form (<user>, <image_name>, <location>),
    # sorted by <user>, then <image_name>, and <location>.
    # since this can take time, we compute all results for one user,
    # then yield them for immediate display.
    def search(self):
        all_users = set()
        # search for local images and users
        local_user_images = defaultdict(set)
        for fullname in self.image_store:
            if self.validate_fullname(fullname, LOCATION_WALT_SERVER):
                user = fullname.split('/')[0]
                all_users.add(user)
                local_user_images[user].add(fullname)
        # search for docker daemon images and users
        docker_daemon_user_images = defaultdict(set)
        for fullname in self.docker.daemon.images():
            if self.validate_fullname(fullname, LOCATION_DOCKER_DAEMON):
                user = fullname.split('/')[0]
                all_users.add(user)
                docker_daemon_user_images[user].add(fullname)
        # search for hub users
        # (detect walt users by their 'walt_metadata' dummy image)
        hub_users = set()
        for waltuser_info in self.docker.hub.search('walt_metadata'):
            if '/walt_metadata' in waltuser_info['name']:
                user = waltuser_info['name'].split('/')[0]
                all_users.add(user)
                hub_users.add(user)
        # search images of each user
        for user in sorted(all_users):
            images_and_labels = defaultdict(dict)
            # search on docker hub
            if user in hub_users:
                # read metadata to detect walt images of this user
                user_metadata = pull_user_metadata(self.docker, user)
                for fullname, info in user_metadata['walt.user.images'].items():
                    if self.validate_fullname(fullname, LOCATION_DOCKER_HUB):
                        image_name = fullname.split('/')[1]
                        images_and_labels[image_name][LOCATION_DOCKER_HUB] = info['labels']
            # search on local server
            for fullname in local_user_images[user]:
                image_user, image_name = fullname.split('/')
                images_and_labels[image_name][LOCATION_WALT_SERVER] = \
                                            self.image_store[fullname].labels
            # search on docker daemon
            for fullname in docker_daemon_user_images[user]:
                image_user, image_name = fullname.split('/')
                images_and_labels[image_name][LOCATION_DOCKER_DAEMON] = \
                                            self.docker.daemon.get_labels(fullname)
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

def clonable_link(location, user, image_name, min_version = None):
    if min_version is not None and min_version > int(__version__):
        return "[Need server upgrade, version>=%d]" % min_version
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
        if user != username or location != LOCATION_WALT_SERVER:
            yield user, image_name, location, labels

def format_result(it):
    for user, image_name, location, labels in it:
        min_version = labels.get('walt.server.minversion', None)
        if min_version is not None:
            try:
                min_version = int(min_version)
            except:
                min_version = None
        node_models = labels['walt.node.models'].split(',')
        yield ( user,
                short_image_name(image_name),
                LOCATION_LONG_LABEL[location],
                format_node_models_list(node_models),
                clonable_link(location, user, image_name, min_version))

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
        # (unless terminal size is too small)
        tty_size = requester.get_win_size()
        for s in columnate_iterate_tty(it, header = SEARCH_HEADER,
                       tty_rows = tty_size['rows'], tty_cols = tty_size['cols']):
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

