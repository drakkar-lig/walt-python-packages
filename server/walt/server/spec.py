import os
import shlex
import shutil
import sys
from pathlib import Path

from plumbum.cmd import chroot
from walt.common.config import load_conf
from walt.common.tools import failsafe_makedirs
from walt.server.tools import update_template

SERVER_SPEC_PATH = Path("/etc/walt/server.spec")
SERVER_SPEC = None
IMAGE_SPEC_PATH = "/etc/walt/image.spec"


def get_server_spec():
    global SERVER_SPEC
    if SERVER_SPEC is None:
        SERVER_SPEC = load_conf(SERVER_SPEC_PATH, optional=True)
        if SERVER_SPEC is None:
            SERVER_SPEC = {}
    return SERVER_SPEC


def reload_server_spec():
    global SERVER_SPEC
    SERVER_SPEC = None
    get_server_spec()


def get_server_features():
    return set(get_server_spec().get("features", []))


def server_has_feature(feature):
    return feature in get_server_features()


def read_image_spec(image_path):
    return load_conf(Path(image_path + IMAGE_SPEC_PATH), optional=True)


def do_chroot(mount_path, cmd):
    args = shlex.split(cmd)
    return chroot(mount_path, *args, retcode=None).strip()


def enable_matching_features(mount_path, image_spec, img_print=print):
    server_feature_set = get_server_features()
    image_feature_set = set(image_spec.get("features", []))
    # intersection of sets
    available_feature_set = server_feature_set & image_feature_set
    for feature in available_feature_set:
        enabling_cmd = image_spec["features"][feature]
        img_print(
            """enabling '%s' feature by running '%s'.""" % (feature, enabling_cmd)
        )
        img_print(do_chroot(mount_path, enabling_cmd))


def update_templates(image_path, image_spec, template_env, img_print=print):
    for template_file in image_spec.get("templates", []):
        template_path = image_path + template_file
        if not Path(template_path).exists():
            img_print(f"WARNING: Template file '{template_file}' "
                       "defined in /etc/walt/image.spec but not found.",
                      file=sys.stderr)
            continue
        update_template(template_path, template_env)


def copy_server_spec_file(image_path):
    target_path = image_path + str(SERVER_SPEC_PATH)
    failsafe_makedirs(os.path.dirname(target_path))
    shutil.copy(SERVER_SPEC_PATH, target_path)
