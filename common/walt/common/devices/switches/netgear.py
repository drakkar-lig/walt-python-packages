NETGEAR_MAC_PREFIX = "6c:b0:ce"
NETGEAR_MAC_PREFIXES = [ "6c:b0:ce", "28:c6:8e", "44:94:fc" ]

class NetgearSwitch(object):
    MAC_PREFIX = NETGEAR_MAC_PREFIX
    MODEL_NAME = "netgear"
    WALT_TYPE  = "switch"
    @staticmethod
    def is_such_a_device(vci, mac):
        #return mac.startswith(NETGEAR_MAC_PREFIX)
        return (len(filter(mac.startswith,NETGEAR_MAC_PREFIXES+[''])[0]) != 0)

def get_device_classes():
    return (NetgearSwitch,)

