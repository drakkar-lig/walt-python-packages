
RPI_MAC_PREFIX = "b8:27:eb"

def rpi_blink(b):
    led_module = "heartbeat" if b else "mmc0"
    with open('/sys/class/leds/led0/trigger', 'w') as f:
        f.write("%s\n" % led_module)

class RPi(object):
    MAC_PREFIX = RPI_MAC_PREFIX
    SHORT_NAME = "rpi"

    @staticmethod
    def blink(b):
        rpi_blink(b)

class RPi2(object):
    MAC_PREFIX = RPI_MAC_PREFIX
    SHORT_NAME = "rpi2"

    @staticmethod
    def blink(b):
        rpi_blink(b)

class RPi3(object):
    MAC_PREFIX = RPI_MAC_PREFIX
    SHORT_NAME = "rpi3"

    @staticmethod
    def blink(b):
        rpi_blink(b)

