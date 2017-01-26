import os, shutil
from walt.common.tools import read_json
from walt.server.threads.main.network.tools import get_server_ip
from walt.server.tools import update_template
from walt.common.tools import failsafe_makedirs


SERVER_SPEC_PATH = '/etc/walt/server.spec'
IMAGE_SPEC_PATH = '/etc/walt/image.spec'

SERVER_SPEC = read_json(SERVER_SPEC_PATH)

def read_image_spec(image_path):
    return read_json(image_path + IMAGE_SPEC_PATH)

def enable_matching_features(image, image_spec):
    try:
        server_feature_set = set(SERVER_SPEC.get('features', []))
        image_feature_set = set(image_spec.get('features', []))
        # intersection of sets
        available_feature_set = server_feature_set & image_feature_set
        for feature in available_feature_set:
            enabling_cmd = image_spec['features'][feature]
            print """enabling '%s' feature by running '%s'.""" % \
                            (feature, enabling_cmd)
            print image.chroot(enabling_cmd)
    except Exception as e:
        print """WARNING: Caught exception '%s'""" % str(e)

def update_templates(image_path, image_spec, template_env):
    for template_file in image_spec.get('templates', []):
        update_template(image_path + template_file, template_env)

def copy_server_spec_file(image_path):
    target_path = image_path + SERVER_SPEC_PATH
    failsafe_makedirs(os.path.dirname(target_path))
    shutil.copy(SERVER_SPEC_PATH, target_path)
