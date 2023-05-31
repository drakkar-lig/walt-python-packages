#!/usr/bin/env python
import sys


def dhcp_commit_event(vci, uci, ip, mac, client_name, mac_is_known, dev_type):
    mac_is_known = int(mac_is_known)
    # we want to:
    # 1. detect new devices (i.e. new mac addresses)
    # 2. allow a device already seen previously but of
    #    unknown type to resend a new notification to
    #    the server to update its type (i.e. become a node)
    # Case 2 is frequent when users first connect a node
    # to the walt network without a proper bootloader set up,
    # then install the bootloader and reconnect the node.
    if mac_is_known:
        if dev_type != "unknown":
            return  # nothing to do, we already know everything
        if not uci.startswith("walt.node.") and not vci.startswith("walt.node."):
            return  # this device of unknown type will remain
            # of unknown type, so do not bother the main
            # daemon with a useless request
    name = None
    if client_name is not None and client_name != "":
        mac_suffix = "".join(mac.split(":"))[-6:]
        if not client_name.endswith(mac_suffix):
            name = f"{client_name}-{mac_suffix}".lower()
    from walt.common.apilink import ServerAPILink

    with ServerAPILink("localhost", "SSAPI") as server:
        server.register_device(vci, uci, ip, mac, name)


def run():
    if sys.argv[1] != "commit":
        print("unexpected dhcp event:", sys.argv[1])
        return
    dhcp_commit_event(*sys.argv[2:])


if __name__ == "__main__":
    run()
