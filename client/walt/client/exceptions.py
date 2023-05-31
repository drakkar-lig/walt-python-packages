class TimeoutException(Exception):
    pass


EXCEPTION_NO_SUCH_IMAGE_NAME = """\
No such WalT image name"""


class NoSuchImageNameException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_NO_SUCH_IMAGE_NAME)


EXCEPTION_NODE_HAS_LOGS = """\
Removing a node with logs without the force parameter is not allowed"""


class NodeHasLogsException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_NODE_HAS_LOGS)


EXCEPTION_NODE_NOT_OWNED = """\
Using a node owned by someone else without the force parameter is not allowed"""


class NodeNotOwnedException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_NODE_NOT_OWNED)


EXCEPTION_NODE_ALREADY_OWNED = """\
This operation does not apply to nodes you already own"""


class NodeAlreadyOwnedException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_NODE_ALREADY_OWNED)


EXCEPTION_OP_APPLIES_NODE_OWNED = """\
This operation only applies to nodes you own"""


class OpAppliesNodeOwnedException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_OP_APPLIES_NODE_OWNED)


EXCEPTION_PARAMETER_NOT_AN_IMAGE = """\
The specified parameter is not a WalT image"""


class ParameterNotAnImageException(Exception):
    def __init__(self):
        super().__init__(EXCEPTION_PARAMETER_NOT_AN_IMAGE)
