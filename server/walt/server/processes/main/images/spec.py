import os
import shlex
import shutil
from pathlib import Path

from plumbum.cmd import chroot
from walt.common.config import load_conf
from walt.common.tools import failsafe_makedirs
from walt.server.spec import SERVER_SPEC_PATH, get_server_features
from walt.server.tools import update_template

IMAGE_SPEC_PATH = "/etc/walt/image.spec"


def read_image_spec(image_path):
    return load_conf(Path(image_path + IMAGE_SPEC_PATH), optional=True)


def do_chroot(mount_path, cmd):
    args = shlex.split(cmd)
    return chroot(mount_path, *args, retcode=None).strip()


def enable_matching_features(mount_path, image_spec):
    try:
        server_feature_set = get_server_features()
        image_feature_set = set(image_spec.get("features", []))
        # intersection of sets
        available_feature_set = server_feature_set & image_feature_set
        for feature in available_feature_set:
            enabling_cmd = image_spec["features"][feature]
            print(
                """enabling '%s' feature by running '%s'.""" % (feature, enabling_cmd)
            )
            print(do_chroot(mount_path, enabling_cmd))
    except Exception as e:
        print("""WARNING: Caught exception '%s'""" % str(e))


def update_templates(image_path, image_spec, template_env):
    for template_file in image_spec.get("templates", []):
        update_template(image_path + template_file, template_env)


def copy_server_spec_file(image_path):
    target_path = image_path + str(SERVER_SPEC_PATH)
    failsafe_makedirs(os.path.dirname(target_path))
    shutil.copy(SERVER_SPEC_PATH, target_path)
