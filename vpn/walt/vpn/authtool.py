#!/usr/bin/env python
import sys

from walt.common.apilink import ServerAPILink


def run():
    if len(sys.argv) < 2:
        print("need <mac address> as first argument.")
        return
    mac = sys.argv[1]
    with ServerAPILink("localhost", "VSAPI") as server:
        response = server.vpn_request_grant(mac)
        print("\n\n".join(response))


if __name__ == "__main__":
    run()
