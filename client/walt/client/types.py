# The following types are used to annotate the arguments
# of walt commands. This annotation is notably used
# to identify the shell completion methods.


# We introduced the following intermediate class STRTYPE
# which instanciates plain str objects, because some of
# these instances are pickled and transmitted to the
# server. If preserving their class, unpickling on server
# side would cause reloading the class definition source
# code (written below in this file), whereas this file should
# only be loaded on client side.
class STRTYPE(str):
    def __new__(cls, s):
        return str(s)


class NODE(STRTYPE):
    pass


class SET_OF_NODES(STRTYPE):
    pass


class IMAGE(STRTYPE):
    pass


class IMAGE_OR_DEFAULT(STRTYPE):
    pass


class NODE_CP_SRC(STRTYPE):
    pass


class NODE_CP_DST(STRTYPE):
    pass


class NODE_CONFIG_PARAM(STRTYPE):
    pass


class DEVICE(STRTYPE):
    pass


class SET_OF_DEVICES(STRTYPE):
    pass


class RESCAN_SET_OF_DEVICES(STRTYPE):
    pass


class DEVICE_CONFIG_PARAM(STRTYPE):
    pass


class HELP_TOPIC(STRTYPE):
    pass


class IMAGE_CP_SRC(STRTYPE):
    pass


class IMAGE_CP_DST(STRTYPE):
    pass


class IMAGE_CLONE_URL(STRTYPE):
    pass


class LOG_CHECKPOINT(STRTYPE):
    pass


class HISTORY_RANGE(STRTYPE):
    pass


class GIT_URL(STRTYPE):
    pass


class DIRECTORY(STRTYPE):
    pass


class IMAGE_BUILD_NAME(STRTYPE):
    pass


class SWITCH(STRTYPE):
    pass


class PORT_CONFIG_PARAM(STRTYPE):
    pass
