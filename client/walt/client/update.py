import os, subprocess, sys
from walt.common.version import __version__
from walt.common.formatting import framed, highlight
from walt.client.plugins import get_plugins

MSG_UPDATE = """
walt-client software does not match server API!
You should update your client using:
$ pip3 install --upgrade "%(package)s==%(remote_version)s"
"""

def check_update(server):
    updated = False
    remote_version = str(server.get_remote_version())
    if remote_version != str(__version__):
        features = [ p.client_feature_name for p in get_plugins() ]
        if len(features) > 0:
            package = 'walt-client[' + ','.join(features) + ']'
        else:
            package = 'walt-client'
        msg = MSG_UPDATE % dict(
                remote_version = remote_version,
                package = package)
        msg = highlight(msg)
        print()
        print(framed('Important notice', msg))
        print()
        sys.exit(1)
