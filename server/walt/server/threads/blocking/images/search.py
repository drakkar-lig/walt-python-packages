from __future__ import annotations

import asyncio
import subprocess
import typing
from collections import defaultdict

from walt.common.formatting import columnate
from walt.common.version import __version__
from walt.server.threads.blocking.images.metadata import \
    async_pull_user_metadata
from walt.server.tools import format_node_models_list, async_merge_generators

if typing.TYPE_CHECKING:
    from walt.server.threads.main.repositories import Repositories
    from walt.server.threads.main.server import Server

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
    def __init__(self, repositories: Repositories, image_store, requester, validate = None):
        self.repositories = repositories
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
    # search yields results in the form (<image_fullname>, <location>, <labels>)
    async def async_search(self):
        async for record in async_merge_generators(
                                self.async_search_walt(),
                                self.async_search_daemon(),
                                self.async_search_hub()
                            ):
            yield record
    async def async_search_walt(self):
        # search for local images
        for fullname in self.image_store:
            if self.validate_fullname(fullname, LOCATION_WALT_SERVER):
                yield (fullname, LOCATION_WALT_SERVER, self.image_store[fullname].labels)
    async def async_search_daemon(self):
        # search for docker daemon images
        if self.repositories.daemon is not None:
            try:
                docker_images = await self.repositories.daemon.async_images()
            except subprocess.CalledProcessError:
                self.requester.stderr.write("Docker daemon is unreachable: it will not be queried. (but docker hub will)")
            else:
                for fullname in docker_images:
                    if self.validate_fullname(fullname, LOCATION_DOCKER_DAEMON):
                        labels = await self.repositories.daemon.async_get_labels(fullname)
                        yield (fullname, LOCATION_DOCKER_DAEMON, labels)
    async def async_search_hub(self):
        # search for hub images
        # (detect walt users by their 'walt_metadata' dummy image)
        generators = []
        async for waltuser_info in self.repositories.hub.async_search('walt_metadata'):
            if '/walt_metadata' in waltuser_info['name']:
                user = waltuser_info['name'].split('/')[0]
                generators += [ self.async_search_hub_user_images(user) ]
        async for record in async_merge_generators(*generators):
            yield record
    async def async_search_hub_user_images(self, user):
        user_metadata = await async_pull_user_metadata(self.repositories, user)
        for fullname, info in user_metadata['walt.user.images'].items():
            if self.validate_fullname(fullname, LOCATION_DOCKER_HUB):
                yield fullname, LOCATION_DOCKER_HUB, info['labels']

def short_image_name(image_name):
    if image_name.endswith(':latest'):
        return image_name[:-7]
    else:
        return image_name

def clonable_link(location, user, image_name, min_version = None):
    try:
        if min_version is not None and min_version > int(__version__):
            return "[Need server upgrade, version>=%d]" % min_version
    except ValueError:  # non-integer dev version
        pass
    return "%s:%s/%s" % (
            LOCATION_LABEL[location],
            user,
            short_image_name(image_name)
    )

async def async_parse_fullnames(it):
    async for fullname, location, labels in it:
        image_user, image_name = fullname.split('/')
        yield image_user, image_name, location, labels

async def async_discard_images_in_ws(it, username):
    # images owned by the requester and present locally on
    # the server are not considered "remote images".
    # (they belong to the working set of the user, instead.)
    async for user, image_name, location, labels in it:
        if user != username or location != LOCATION_WALT_SERVER:
            yield user, image_name, location, labels

async def async_format_result(it):
    async for user, image_name, location, labels in it:
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
async def async_perform_search(repositories: Repositories, image_store, requester, keyword, tty_mode):
    username = requester.get_username()
    if not username:
        return None    # client already disconnected, give up
    if keyword:
        def validate(image_name, user, location):
            return keyword in clonable_link(location, user, image_name)
    else:
        validate = None
    # search
    search = Search(repositories, image_store, requester, validate)
    it = search.async_search()
    it = async_parse_fullnames(it)
    it = async_discard_images_in_ws(it, username)
    it = async_format_result(it)

    rows = []
    async for t in it:
        rows.append(t)
        if tty_mode:
            requester.stdout.write(f'{len(rows)} matches\r')
    if len(rows) > 0:
        s = columnate(rows, SEARCH_HEADER)
        requester.stdout.write(s + '\n')
    else:
        requester.stderr.write(MSG_SEARCH_NO_MATCH)

# this implements walt image search
def search(requester, server: Server, keyword, tty_mode):
    return asyncio.run(async_perform_search(
            server.repositories, server.images.store, requester, keyword, tty_mode))

