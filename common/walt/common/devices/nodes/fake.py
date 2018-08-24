
class Fake(object):
    MAC_PREFIX = "xx:xx:xx"
    MODEL_NAME = "fake"
    WALT_TYPE  = "node"
    @staticmethod
    def is_such_a_device(vci, mac):
        return False

def get_device_classes():
    return (Fake,)

