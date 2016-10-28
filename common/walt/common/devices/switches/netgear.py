NETGEAR_MAC_PREFIX = "6c:b0:ce"

class NetgearSwitch(object):
    MAC_PREFIX = NETGEAR_MAC_PREFIX
    MODEL_NAME = "netgear"
    WALT_TYPE  = "switch"
    @staticmethod
    def is_such_a_device(vci, mac):
        return mac.startswith(NETGEAR_MAC_PREFIX)

def get_device_classes():
    return (NetgearSwitch,)

