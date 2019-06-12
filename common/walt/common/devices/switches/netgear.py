NETGEAR_MAC_PREFIXES = [ "6c:b0:ce", "28:c6:8e", "44:94:fc" ]

class NetgearSwitch(object):
    MODEL_NAME = "netgear"
    WALT_TYPE  = "switch"
    @staticmethod
    def is_such_a_device(vci, mac):
        return max(mac.startswith(prefix) for prefix in NETGEAR_MAC_PREFIXES)

def get_device_classes():
    return (NetgearSwitch,)

