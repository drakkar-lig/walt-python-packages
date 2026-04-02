#!/usr/bin/env python
import sys
from walt.server.tools import SSAPILink

method_name = sys.argv[1]
args = sys.argv[2:]

with SSAPILink() as server:
    method = getattr(server, method_name)
    method(*args)
