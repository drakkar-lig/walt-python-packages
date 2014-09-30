
class RPi(object):
    MAC_PREFIX = "b8:27:eb"
    SHORT_NAME = "rpi"

    @staticmethod
    def blink(bool):
        led_module = "heartbeat" if bool else "mmc0"
        with open('/sys/class/leds/led0/trigger', 'w') as f:
            f.write("%s\n" % led_module)


