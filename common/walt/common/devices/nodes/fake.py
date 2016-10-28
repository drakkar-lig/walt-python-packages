
class Fake(object):
    MAC_PREFIX = "xx:xx:xx"
    MODEL_NAME = "fake"
    WALT_TYPE  = "node"
    @staticmethod
    def is_such_a_device(vci, mac):
        return False
    @staticmethod
    def blink(bool):
        if bool:
            print "Starting to blink."
        else:
            print "Stopped blinking."

def get_device_classes():
    return (Fake,)

