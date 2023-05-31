import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from subprocess import CalledProcessError

from podman import PodmanClient
from podman.errors.exceptions import ImageNotFound
from walt.server.exttools import buildah, findmnt, mount, podman, umount
from walt.server.tools import add_image_repo, format_node_models_list

MAX_IMAGE_LAYERS = 128
METADATA_CACHE_FILE = Path("/var/cache/walt/images.metadata")
IMAGE_LAYERS_DIR = "/var/lib/containers/storage/overlay"
PODMAN_API_SOCKET = "unix:///run/walt/podman/podman.socket"


def parse_date(created_at):
    # strptime does not support parsing nanosecond precision
    # remove last 3 decimals of this number
    created_at = re.sub(r"([0-9]{6})[0-9]*", r"\1", created_at)
    dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S.%f %z %Z")
    # remove subsecond precision (not needed)
    dt = dt.replace(microsecond=0)
    # convert to local time
    return str(dt.astimezone().replace(tzinfo=None))


# 'buildah mount' does not mount the overlay filesystem with appropriate options to
# allow nfs export. let's fix this.
def remount_with_nfs_export_option(mountpoint):
    # retrieve mount info
    json_info = findmnt("--json", mountpoint)
    mount_info = json.loads(json_info)["filesystems"][0]
    source = mount_info["source"]
    fstype = mount_info["fstype"]
    options = mount_info["options"].split(",")
    # update options
    new_options = ["rw", "relatime", "index=on", "nfs_export=on"] + [
        opt
        for opt in options
        if opt.startswith("lowerdir")
        or opt.startswith("upperdir")
        or opt.startswith("workdir")
    ]
    # umount
    umount(mountpoint)
    # overlay has a check in place to prevent mounting the same file system
    # twice if volatile was already specified.
    for opt in options:
        if opt.startswith("workdir"):
            workdir = Path(opt[len("workdir=") :])
            incompat_volatile = workdir / "work" / "incompat" / "volatile"
            if incompat_volatile.exists():
                shutil.rmtree(incompat_volatile)
            break
    # when having many layers, podman specifies them relative to the
    # following directory
    os.chdir(IMAGE_LAYERS_DIR)
    # re-mount
    mount("-t", fstype, "-o", ",".join(new_options), source, mountpoint)


def mount_exists(mountpoint):
    try:
        findmnt("--json", mountpoint)
    except CalledProcessError:
        return False
    return True


class WalTLocalRegistry:
    def __init__(self):
        self.names_cache = {}

    def prepare(self):
        self.metadata_cache = self.load_metadata_cache_file()
        self.p = PodmanClient(base_url=PODMAN_API_SOCKET)
        self.scan()

    def load_metadata_cache_file(self):
        if METADATA_CACHE_FILE.exists():
            metadata = json.loads(METADATA_CACHE_FILE.read_text())
            if len(metadata) > 0:
                # check compatibility with the format expected with current code
                first_entry = tuple(metadata.values())[0]
                if "node_models_desc" in first_entry:
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
        created_at_ts = (
            data.attrs["Created"].replace("T", " ").replace("Z", " +0000 UTC")
        )
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
        return dict(
            labels=labels,
            editable=(num_layers < MAX_IMAGE_LAYERS),
            image_id=image_id,
            created_at=parse_date(created_at_ts),
            node_models=node_models,
            node_models_desc=node_models_desc,
        )

    def image_exists(self, fullname):
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
            self.metadata_cache[image_id] = self.deep_inspect(image_id)
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
        image_id = self.names_cache.get(fullname)
        if image_id is None:
            im = self.get_podman_image(fullname)
            if im is not None:
                self.refresh_names_cache_for_image(im)
                image_id = self.names_cache.get(fullname)
        if image_id is None:
            print(f"get_metadata() failed for {fullname}: image not found")
            return None
        if image_id not in self.metadata_cache:
            self.metadata_cache[image_id] = self.deep_inspect(image_id)
        return self.metadata_cache[image_id]

    def stop_container(self, cont_name):
        podman.rm("-f", "-i", cont_name)

    def events(self):
        return podman.events.stream(
            "--format", "json", converter=(lambda line: json.loads(line))
        )

    def get_mount_container_name(self, image_id):
        return "mount:" + image_id[:12]

    def get_mount_image_name(self, image_id):
        return "localhost/walt/mounts:" + image_id[:12]

    def image_mount(self, image_id, mount_path):
        # if server daemon was killed and restarted, the mount may still be there
        if mount_exists(mount_path):
            return False  # nothing to do
        # in some cases the code may remove the last tag of an image whilst it is
        # still mounted, waiting for grace time expiry. this fails.
        # in order to avoid this we attach a new tag to all images we mount.
        image_name = self.get_mount_image_name(image_id)
        if not self.image_exists(image_name):
            self.ll_podman_tag(str(image_id), image_name)
        # create a buildah container and use the buildah mount command
        cont_name = self.get_mount_container_name(image_id)
        try:
            buildah("from", "--pull-never", "--name", cont_name, image_id)
        except CalledProcessError:
            print(
                "Note: walt server was probably not stopped properly and container"
                " still exists. Going on."
            )
        dir_name = buildah.mount(cont_name)
        remount_with_nfs_export_option(dir_name)
        mount("--bind", dir_name, mount_path)
        return True

    def image_umount(self, image_id, mount_path):
        cont_name = self.get_mount_container_name(image_id)
        if mount_exists(mount_path):
            umount("-lf", mount_path)
        buildah.umount(cont_name)
        buildah.rm(cont_name)
        image_name = self.get_mount_image_name(image_id)
        self.p.images.remove(image_name)
