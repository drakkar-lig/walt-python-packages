
RPI_MAC_PREFIX = "b8:27:eb"

def rpi_blink(b):
    led_module = "heartbeat" if b else "mmc0"
    with open('/sys/class/leds/led0/trigger', 'w') as f:
        f.write("%s\n" % led_module)

def create_rpi_class(cls_name, model):
    # class static methods
    def is_such_a_device(vci, mac):
        return vci == model
    def blink(b):
        rpi_blink(b)
    # class creation
    return type(cls_name, (), dict(
        MAC_PREFIX = RPI_MAC_PREFIX,
        MODEL_NAME = model,
        WALT_TYPE  = "node",
        is_such_a_device = staticmethod(is_such_a_device),
        blink = staticmethod(blink)
    ))
    
# creation of one class for each model
RpiB = create_rpi_class('RpiB', 'rpi-b')
RpiBPlus = create_rpi_class('RpiBPlus', 'rpi-b-plus')
Rpi2B = create_rpi_class('Rpi2B', 'rpi-2-b')
Rpi3B = create_rpi_class('Rpi3B', 'rpi-3-b')

def get_device_classes():
    return (RpiB, RpiBPlus, Rpi2B, Rpi3B)

