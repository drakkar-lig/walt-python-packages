NETGEAR_MAC_PREFIXES = ["6c:b0:ce", "28:c6:8e", "44:94:fc"]


def probe(mac):
    if any(mac.startswith(prefix) for prefix in NETGEAR_MAC_PREFIXES):
        return {"type": "switch", "model": "netgear"}
