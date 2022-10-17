#!/usr/bin/env python
import sys
from walt.common.apilink import ServerAPILink

def register_device(vci, uci, ip, mac, client_name=None):
    name = None
    if client_name is not None and client_name != '':
        mac_suffix = ''.join(mac.split(':'))[-6:]
        name = f'{client_name}-{mac_suffix}'.lower()
    with ServerAPILink('localhost', 'SSAPI') as server:
        server.register_device(vci, uci, ip, mac, name)

def run():
    if sys.argv[1] != 'commit':
        print('unexpected dhcp event:', sys.argv[1])
        return
    register_device(*sys.argv[2:])

if __name__ == "__main__":
    run()

