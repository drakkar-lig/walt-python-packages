#!/usr/bin/env python
import sys
from walt.server.tools import SSAPILink

dev_name = sys.argv[1]
if len(sys.argv) == 4:
    dev_type = sys.argv[2]
    model = sys.argv[3]
else:
    dev_type = "unknown"
    model = ""

with SSAPILink() as server:
    mac, ip = server.register_fake_device(
                    type=dev_type,
                    model=model,
                    name=dev_name)
    if mac is None or ip is None:
        sys.exit(1)  # issue already reported
    print(f"mac: {mac}")
    print(f"ip: {ip}")
