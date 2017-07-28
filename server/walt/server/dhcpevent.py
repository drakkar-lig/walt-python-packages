#!/usr/bin/env python
import sys
from walt.common.apilink import ServerAPILink

def run():
    if sys.argv[1] != 'commit':
        print 'unexpected dhcp event:', sys.argv[1]
        return
    vci, uci, ip, mac = sys.argv[2:]
    with ServerAPILink('localhost', 'SSAPI') as server:
        server.register_device(vci, uci, ip, mac)

if __name__ == "__main__":
    run()

