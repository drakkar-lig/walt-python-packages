
class Fake(object):
    MAC_PREFIX = "xx:xx:xx"
    SHORT_NAME = "fake"

    @staticmethod
    def blink(bool):
        if bool:
            print "Starting to blink."
        else:
            print "Stopped blinking."


