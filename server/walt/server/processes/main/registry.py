import json
from pathlib import Path

from podman import PodmanClient
from podman.errors.exceptions import ImageNotFound
from walt.server.exttools import podman
from walt.server.tools import add_image_repo, format_node_models_list
from walt.server.tools import parse_date, get_podman_client

MAX_IMAGE_LAYERS = 128
METADATA_CACHE_FILE = Path("/var/cache/walt/images.metadata")


def date_to_str_local(dt):
    # remove subsecond precision (not needed)
    dt = dt.replace(microsecond=0)
    # convert to local time
    return str(dt.astimezone().replace(tzinfo=None))


class WalTLocalRegistry:
    def __init__(self):
        self.names_cache = {}

    def prepare(self):
        self.metadata_cache = self.load_metadata_cache_file()
        self.p = get_podman_client()
        self.scan()

    def load_metadata_cache_file(self):
        if METADATA_CACHE_FILE.exists():
            metadata = json.loads(METADATA_CACHE_FILE.read_text())
            if len(metadata) > 0:
                # check compatibility with the format expected with current code
                first_entry = tuple(metadata.values())[0]
                if "created_ts" in first_entry:
                    # all is fine
                    return metadata
        return {}

    def save_metadata_cache_file(self):
        if not METADATA_CACHE_FILE.exists():
            METADATA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        METADATA_CACHE_FILE.write_text(json.dumps(self.metadata_cache))

    def add_repo(self, fullname):
        if fullname.startswith("walt/"):
            return "localhost/" + fullname
        else:
            return "docker.io/" + fullname

    def ll_podman_tag(self, old_fullname_or_id, repo_fullname):
        new_args = repo_fullname.split(":")  # split image_repo_name and image_tag
        self.p.images.get(old_fullname_or_id).tag(*new_args)

    def tag(self, old_fullname, new_fullname):
        if self.image_exists(new_fullname):
            # take care not making previous version of image a dangling image
            self.p.images.remove(add_image_repo(new_fullname))
        if old_fullname in self.names_cache:
            self.names_cache[new_fullname] = self.names_cache[old_fullname]
        else:
            self.names_cache.pop(new_fullname, None)
        self.ll_podman_tag(old_fullname, add_image_repo(new_fullname))

    def rmi(self, fullname, ignore_missing=False):
        self.untag(fullname, ignore_missing=ignore_missing)

    def untag(self, fullname, ignore_missing=False):
        if ignore_missing and not self.image_exists(fullname):
            return  # nothing to do
        self.p.images.remove(add_image_repo(fullname))
        self.names_cache.pop(fullname, None)

    def deep_inspect(self, image_id):
        print("deep_inspect", image_id)
        data = self.p.images.get_registry_data(image_id)
        labels = data.attrs["Labels"]
        if labels is None:
            labels = {}
        created_ts = data.attrs["Created"]
        if "walt.node.models" in labels:
            node_models = labels["walt.node.models"].split(",")
            node_models_desc = format_node_models_list(node_models)
        else:
            node_models = None
            node_models_desc = "N/A"
        layers = data.attrs["RootFS"]["Layers"]
        if layers is None:
            num_layers = 0
        else:
            num_layers = len(layers)
        size_kib = data.attrs['Size'] // 1024
        dt = parse_date(created_ts)
        return dict(
            labels=labels,
            editable=(num_layers < MAX_IMAGE_LAYERS),
            image_id=image_id,
            created_at=date_to_str_local(dt),
            created_ts=dt.timestamp(),
            node_models=node_models,
            node_models_desc=node_models_desc,
            size_kib=size_kib,
            digest=data.attrs["Digest"]
        )

    def image_exists(self, fullname):
        if fullname in self.names_cache:
            return True
        else:  # slow path
            return self.get_podman_image(fullname) is not None

    def get_podman_image(self, fullname):
        try:
            return self.p.images.get(add_image_repo(fullname))
        except ImageNotFound:
            return None

    def refresh_names_cache_for_image(self, im):
        for podman_image_name in im.tags:
            # podman may manage several repos, we do not need it here, discard
            # this repo prefix
            fullname = podman_image_name.split("/", 1)[1]
            if "/" not in fullname:
                continue
            self.names_cache[fullname] = im.id
            print(f"found {fullname} -- {im.id}")

    def scan(self):
        print("scanning images...")
        self.names_cache = {}
        for im in self.p.images.list(filters={"dangling": False}):
            self.refresh_names_cache_for_image(im)
        old_metadata_cache = self.metadata_cache
        self.metadata_cache = {}
        missing_ids = set()
        for image_id in set(self.names_cache.values()):
            if image_id in self.metadata_cache:
                continue
            if image_id in old_metadata_cache:
                self.metadata_cache[image_id] = old_metadata_cache[image_id]
                continue
            missing_ids.add(image_id)
        for image_id in missing_ids:
            try:
                self.metadata_cache[image_id] = self.deep_inspect(image_id)
            except Exception:
                print(f"WARNING: inspecting podman image {image_id} failed. Ignored.")
        self.save_metadata_cache_file()
        print("done scanning images.")

    def get_images(self):
        for fullname, image_id in self.names_cache.items():
            if fullname.startswith("walt/"):
                continue
            if self.metadata_cache[image_id]["node_models"] is None:
                continue
            yield fullname

    def refresh_cache_for_image(self, fullname):
        self.names_cache.pop(fullname, None)
        self.get_metadata(fullname)

    def get_metadata(self, fullname):
        return self.get_multiple_metadata((fullname,))[0]

    def get_multiple_metadata(self, fullnames):
        image_ids = list(map(self.names_cache.get, fullnames))
        if None in image_ids:
            # slow path
            for idx, info in enumerate(zip(fullnames, image_ids.copy())):
                fullname, image_id = info
                if image_id is None:
                    im = self.get_podman_image(fullname)
                    if im is not None:
                        self.refresh_names_cache_for_image(im)
                        image_id = self.names_cache.get(fullname)
                    if image_id is None:
                        print(f"get_metadata() failed for {fullname}: image not found")
                    else:
                        image_ids[idx] = image_id
        images_metadata = list(map(self.metadata_cache.get, image_ids))
        if None in images_metadata:
            # slow path
            for idx, info in enumerate(zip(image_ids, images_metadata.copy())):
                image_id, metadata = info
                if image_id is not None and metadata is None:
                    metadata = self.deep_inspect(image_id)
                    self.metadata_cache[image_id] = metadata
                    images_metadata[idx] = metadata
        return images_metadata

    def stop_container(self, cont_name):
        podman.rm("-f", "-i", cont_name)

    def events(self):
        return podman.events.stream(
            "--format", "json", converter=(lambda line: json.loads(line))
        )
