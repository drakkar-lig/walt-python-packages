from __future__ import annotations

import asyncio
import typing

from walt.common.formatting import columnate
from walt.common.version import __version__
from walt.server import conf
from walt.server.exttools import docker
from walt.server.processes.blocking.images.metadata import async_pull_user_metadata
from walt.server.processes.blocking.registries import (
    DockerHubClient,
    DockerDaemonClient,
    get_registry_client,
    MissingRegistryCredentials,
)
from walt.server.tools import async_merge_generators, format_node_models_list

if typing.TYPE_CHECKING:
    from walt.server.processes.main.server import Server

# About terminology: See comment about it in image.py.

SEARCH_HEADER = ["User", "Image name", "Location", "Compatibility", "Clonable link"]
MSG_SEARCH_NO_MATCH = "Sorry, no image could match your request.\n"


def location_long_label(location):
    return {
        "walt": "walt (other user)",
        "hub": "docker hub",
        "docker": "docker daemon",
    }.get(location, "custom registry")


# in order to efficiently search for walt images on the docker hub,
# each walt user has a dummy image called 'walt_metadata' pushed on
# its docker hub account. This image is refreshed each time an image
# is published with "walt image publish".


class Search(object):
    def __init__(self, image_store, requester, validate=None, output_registries=False):
        self.image_store = image_store
        self.requester = requester
        self.output_registries = output_registries
        if validate is None:

            def validate(user, name, location):
                return True

        self.validate = validate

    def validate_fullname(self, fullname, location):
        parts = fullname.split("/")
        if len(parts) != 2:
            return False
        user, image_name = parts
        return self.validate(image_name, user, location)

    # search yields results in the form (<image_fullname>, <location>, <labels>)
    # or (<registry>, <image_fullname>, <location>, <labels>) if
    # output_registries was set to True.
    async def async_search(self):
        generators = []
        if self.image_store is not None:
            generators += [self.async_search_walt()]
        if docker is not None:
            generators += [self.async_search_daemon()]
        for reg_info in conf["registries"]:
            registry = get_registry_client(self.requester, reg_info["label"])
            if registry is None:  # problem with the configuration (already reported)
                continue
            api = reg_info["api"]
            if api == "docker-hub":
                generators += [self.async_search_hub(registry)]
            else:
                generators += [self.async_search_registry_v2(registry)]
            # First-time logins will require the user to input its credentials,
            # so fail early if they are missing
            if registry.op_needs_authentication("search"):
                self.requester.ensure_registry_conf_has_credentials(
                                    registry.label)
        async for record in async_merge_generators(*generators):
            yield record

    async def async_search_walt(self):
        # search for local images
        for fullname, labels in self.image_store.get_labels().items():
            if self.validate_fullname(fullname, "walt"):
                if self.output_registries:
                    raise NotImplementedError(
                        "Local walt image repo does not "
                        "implement the same registry API.")
                else:
                    yield (fullname, "walt", labels)

    async def async_search_daemon(self):
        try:
            # search for docker daemon images
            docker_daemon = DockerDaemonClient()
            docker_images = await docker_daemon.async_images()
            for fullname in docker_images:
                if self.validate_fullname(fullname, "docker"):
                    labels = await docker_daemon.async_get_labels(
                        self.requester, fullname
                    )
                    if self.output_registries:
                        yield (docker_daemon, fullname, "docker", labels)
                    else:
                        yield (fullname, "docker", labels)
        except Exception:
            self.requester.stderr.write(
                "Ignoring images of docker daemon because of a communication failure.\n"
            )
            return

    async def async_search_hub(self, hub):
        try:
            # search for hub images
            # (detect walt users by their 'walt_metadata' dummy image)
            generators = []
            async for waltuser_info in hub.async_search("walt_metadata"):
                if "/walt_metadata" in waltuser_info["name"]:
                    user = waltuser_info["name"].split("/")[0]
                    generators += [self.async_search_hub_user_images(hub, user)]
            async for record in async_merge_generators(*generators):
                if self.output_registries:
                    record = (hub,) + record
                yield record
        except Exception:
            self.requester.stderr.write(
                "Ignoring hub registry because of a communication failure.\n"
            )
            return

    async def async_search_hub_user_images(self, hub, user):
        user_metadata = await async_pull_user_metadata(hub, user)
        for fullname, info in user_metadata["walt.user.images"].items():
            if self.validate_fullname(fullname, "hub"):
                yield fullname, "hub", info["labels"]

    async def async_search_registry_v2(self, registry):
        try:
            generators = []
            async for image_name in registry.async_catalog(self.requester):
                generators += [
                    self.async_get_registry_v2_image_tags(registry, image_name)
                ]
            async for record in async_merge_generators(*generators):
                if self.output_registries:
                    record = (registry,) + record
                yield record
        except Exception:
            self.requester.stderr.write(
                f"Ignoring {registry.label} registry because of a communication"
                " failure.\n"
            )
            return

    async def async_get_registry_v2_image_tags(self, registry, image_name):
        async for tag in registry.async_list_image_tags(self.requester, image_name):
            fullname = f"{image_name}:{tag}"
            if self.validate_fullname(fullname, registry.label):
                labels = await registry.async_get_labels(self.requester, fullname)
                yield fullname, registry.label, labels


def short_image_name(image_name):
    if image_name.endswith(":latest"):
        return image_name[:-7]
    else:
        return image_name


def clonable_link(location, user, image_name, min_version=None):
    v = __version__.split('+')[0]
    try:
        if (min_version is not None and
            float(v) >= 1.0 and   # bypass the check if dev version
            float(min_version) > float(v)):
            return f"[Need server upgrade, version>={min_version}]"
    except Exception:
        print("Ignoring invalid image label 'walt.server.minversion'")
    return "%s:%s/%s" % (location, user, short_image_name(image_name))


async def async_filter_walt_images(it):
    async for fullname, location, labels in it:
        if "walt.node.models" in labels:
            yield fullname, location, labels


async def async_parse_fullnames(it):
    async for fullname, location, labels in it:
        parts = fullname.split("/")
        if len(parts) != 2:
            continue
        image_user, image_name = parts
        yield image_user, image_name, location, labels


async def async_discard_images_in_ws(it, username):
    # images owned by the requester and present locally on
    # the server are not considered "remote images".
    # (they belong to the working set of the user, instead.)
    async for user, image_name, location, labels in it:
        if user != username or location != "walt":
            yield user, image_name, location, labels


async def async_format_result(it):
    async for user, image_name, location, labels in it:
        min_version = labels.get("walt.server.minversion", None)
        if min_version is not None:
            try:
                min_version = int(min_version)
            except Exception:
                min_version = None
        node_models = labels["walt.node.models"].split(",")
        yield (
            user,
            short_image_name(image_name),
            location_long_label(location),
            format_node_models_list(node_models),
            clonable_link(location, user, image_name, min_version),
        )


# this implements walt image search
async def async_perform_search(image_store, requester, keyword, tty_mode):
    username = requester.get_username()
    if not username:
        return None  # client already disconnected, give up
    if keyword:

        def validate(image_name, user, location):
            return keyword in clonable_link(location, user, image_name)

    else:
        validate = None
    # search
    search = Search(image_store, requester, validate)
    it = search.async_search()
    it = async_filter_walt_images(it)
    it = async_parse_fullnames(it)
    it = async_discard_images_in_ws(it, username)
    it = async_format_result(it)

    rows = []
    async for t in it:
        rows.append(t)
        if tty_mode:
            requester.stdout.write(f"{len(rows)} matches\r")
    if len(rows) > 0:
        s = columnate(rows, SEARCH_HEADER)
        requester.stdout.write(s + "\n")
    else:
        requester.stderr.write(MSG_SEARCH_NO_MATCH)


# this implements walt image search
def search(requester, server: Server, keyword, tty_mode):
    hub = DockerHubClient()
    try:
        # login to the docker hub (we can pull anonymously,
        # but with a low pull rate limit)
        requester.ensure_registry_conf_has_credentials('hub')
        hub.login(requester)
        # perform all the pulls asynchronously
        asyncio.run(
            async_perform_search(server.images.store, requester, keyword, tty_mode)
        )
    except MissingRegistryCredentials as e:
        return ('MISSING_REGISTRY_CREDENTIALS', e.registry_label)
    return ('OK',)
