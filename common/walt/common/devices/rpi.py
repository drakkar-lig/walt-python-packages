
RPI_MAC_PREFIX = "b8:27:eb"

def rpi_blink(b):
    led_module = "heartbeat" if b else "mmc0"
    with open('/sys/class/leds/led0/trigger', 'w') as f:
        f.write("%s\n" % led_module)

class RPiB(object):
    MAC_PREFIX = RPI_MAC_PREFIX
    SHORT_NAME = "rpi-b"

    @staticmethod
    def blink(b):
        rpi_blink(b)

class RPiBPlus(object):
    MAC_PREFIX = RPI_MAC_PREFIX
    SHORT_NAME = "rpi-b-plus"

    @staticmethod
    def blink(b):
        rpi_blink(b)

class RPi2B(object):
    MAC_PREFIX = RPI_MAC_PREFIX
    SHORT_NAME = "rpi-2-b"

    @staticmethod
    def blink(b):
        rpi_blink(b)

class RPi3B(object):
    MAC_PREFIX = RPI_MAC_PREFIX
    SHORT_NAME = "rpi-3-b"

    @staticmethod
    def blink(b):
        rpi_blink(b)

