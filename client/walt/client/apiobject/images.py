import re
import sys
from collections import defaultdict
from pathlib import Path

from walt.client.apiobject.base import (
    APIItemClassFactory,
    APIItemInfoCache,
    APIObjectBase,
    APISetOfItemsClassFactory,
)
from walt.client.apitools import silent_server_link
from walt.client.config import conf
from walt.client.exceptions import NoSuchImageNameException
from walt.client.transfer import run_transfer_for_image_build
from walt.common.tools import parse_image_fullname


class APIImageInfoCache(APIItemInfoCache):
    def __init__(self):
        super().__init__(show_aliases=True)

    def do_refresh(self, server):
        fields = ("id", "name", "fullname", "in_use", "created", "compatibility:tuple")
        tabular_data = server.get_images_tabular_data(
            conf.walt.username, refresh=False, fields=fields
        )
        # remove ':<suffix>' on field names
        fields = list(re.sub(r"([^:]*):.*", r"\1", f) for f in fields)
        # replace rows with dicts
        image_infos = list(
            {f: val for f, val in zip(fields, row)} for row in tabular_data
        )
        # populate attributes
        self.info_per_id = {}
        self.id_per_name = {}
        self.names_per_id = defaultdict(set)
        for info in image_infos:
            name = info.pop("name")
            image_id = info["id"]
            self.id_per_name[name] = image_id
            self.info_per_id[image_id] = info
            self.names_per_id[image_id].add(name)

    def do_remove_item(self, server, item_name):
        return server.remove_image(item_name)

    def do_rename_item(self, server, item_name, new_item_name):
        return server.rename_image(item_name, new_item_name)


__info_cache__ = APIImageInfoCache()


class APIImageBase:
    """Base class of all APIImage classes, for use in isinstance()"""

    pass


class APISetOfImagesBase:
    """Base class of all APISetOfImages classes, for use in isinstance()"""

    pass


class APIImageFactory:
    __images_per_name__ = {}

    @staticmethod
    def create(in_image_name):
        api_image = APIImageFactory.__images_per_name__.get(in_image_name)
        if api_image is not None:
            return api_image
        item_cls = APIItemClassFactory.create(
            __info_cache__, in_image_name, "image", APIImageBase, APISetOfImagesFactory
        )

        class APIImage(item_cls, APIImageBase):
            def remove(self):
                name = self.name
                self.__remove_from_cache__()
                if name in __info_cache__:
                    return  # __remove_from_cache__ failed
                del APIImageFactory.__images_per_name__[name]

            def rename(self, new_name):
                name = self.name
                self.__rename_in_cache__(new_name)
                if name in __info_cache__:
                    return  # __rename_in_cache__ failed
                APIImageFactory.__images_per_name__[new_name] = (
                    APIImageFactory.__images_per_name__.pop(name)
                )

        api_image = APIImage()
        APIImageFactory.__images_per_name__[in_image_name] = api_image
        __info_cache__.register_obj(api_image)
        return api_image


class APISetOfImagesFactory:
    @classmethod
    def create(item_set_factory, in_names):
        item_set_cls = APISetOfItemsClassFactory.create(
            __info_cache__,
            in_names,
            "image",
            APIImageBase,
            APIImageFactory,
            APISetOfImagesBase,
            item_set_factory,
        )

        class APISetOfImages(item_set_cls, APISetOfImagesBase):
            """Set of WalT images"""

            pass

        return APISetOfImages()


class APIImagesSubModule(APIObjectBase):
    """API submodule for WALT images"""

    def get_images(self):
        """Return images of your working set"""
        return get_images()

    def build(self, image_name, dir_or_url):
        """Build an image using a Dockerfile"""
        mode = "dir" if Path(dir_or_url).exists() else "url"
        info = dict(mode=mode, image_name=image_name)
        if mode == "dir":
            if not Path(dir_or_url).is_dir():
                sys.stderr.write(
                    "Failed: parameter dir_or_url must be a directory or a git"
                    " repository URL.\n"
                )
                return
            info["src_dir"] = str(dir_or_url)
        else:
            info["url"] = dir_or_url
        with silent_server_link() as server:
            info = server.create_image_build_session(**info)
            if info is None:
                return  # issue already reported
            image_overwrite = info.pop("image_overwrite")
            if image_overwrite:
                sys.stderr.write("Failed: An image with this name already exists.\n")
                return
            session_id = info.pop("session_id")
            if mode == "dir":
                try:
                    if not run_transfer_for_image_build(**info):
                        return
                except (KeyboardInterrupt, EOFError):
                    print()
                    print("Aborted.")
                    return
            else:
                if not server.run_image_build_from_url(session_id):
                    # failed
                    return
            server.finalize_image_build_session(session_id)
        __info_cache__.refresh()  # detect the new image
        return APIImageFactory.create(image_name)

    def clone(self, clonable_image_link, force=False, image_name=None):
        """Clone a remote image into your working set"""
        with silent_server_link() as server:
            res = server.clone_image(
                clonable_image_link, force=force, image_name=image_name
            )
            if res["status"] == "OK":
                __info_cache__.refresh()  # detect the new image
                image_name = res["image_name"]
                print("The image was cloned successfully.")
                return APIImageFactory.create(image_name)
            else:
                return  # issue


class APIClonableImage(APIObjectBase):
    def clone(self, force=False, image_name=None):
        """Clone this image into your working set"""
        images_submodule = get_api_images_submodule()
        return images_submodule.clone(
            self.clonable_link, force=force, image_name=image_name
        )


class APIDefaultImage(APIClonableImage):
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.owner = "waltplatform"
        self.fullname = f"waltplatform/{model}-default:latest"
        self.clonable_link = f"walt:{self.fullname}"
        self.__doc__ = f"default for {self.model} nodes"


class APIOtherUserImage(APIClonableImage):
    def __init__(self, fullname):
        super().__init__()
        self.fullname, self.owner, self.name = parse_image_fullname(fullname)
        self.clonable_link = f"walt:{self.fullname}"
        self.__doc__ = f'''{self.owner}'s "{self.name}"'''


def get_image_object_from_fullname(image_fullname):
    image_fullname, image_user, image_name = parse_image_fullname(image_fullname)
    if image_user == "waltplatform" and image_name.endswith("-default"):
        model = image_fullname[len("waltplatform/") : -len("-default:latest")]
        return APIDefaultImage(model)
    elif image_user != conf.walt.username:
        return APIOtherUserImage(image_fullname)
    else:
        return APIImageFactory.create(image_name)


def get_image_from_name(image_name):
    """Return the image having given name"""
    api_images = get_images()
    image = api_images.get(image_name, None)
    if image is None:
        raise NoSuchImageNameException()
    return image


def get_images():
    """Return images of your working set"""
    names = set(__info_cache__.names())
    return APISetOfImagesFactory.create(names)


def update_image_cache():
    __info_cache__.refresh()


def get_api_images_submodule():
    return APIImagesSubModule()
