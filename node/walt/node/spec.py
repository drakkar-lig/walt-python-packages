import subprocess
from walt.common.tools import read_json

SERVER_SPEC = read_json('/etc/walt/server.spec')
IMAGE_SPEC = read_json('/etc/walt/image.spec')

def enable_matching_features():
    # If one of the spec files is missing, this means
    # we are using an old image or an old server set up
    # before this handling of optional features was
    # implemented: thus no optional feature is available.
    if None in [ SERVER_SPEC, IMAGE_SPEC ]:
        return
    try:
        # being here means both spec files are available
        server_feature_set = set(SERVER_SPEC['features'])
        image_feature_set = set(IMAGE_SPEC['features'])
        # intersection of sets
        available_feature_set = server_feature_set & image_feature_set
        for feature in available_feature_set:
            enabling_cmd = IMAGE_SPEC['features'][feature]
            print """enabling '%s' feature by running '%s'.""" % \
                            (feature, enabling_cmd)
            print subprocess.check_output(enabling_cmd, shell=True)
    except Exception as e:
        print """WARNING: Caught exception '%s'""" % str(e)

