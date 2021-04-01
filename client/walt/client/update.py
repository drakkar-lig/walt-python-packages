import os, subprocess
from walt.common.version import __version__
from walt.common.formatting import framed, highlight
from walt.client.plugins import get_plugins

MSG_UPDATE = """
walt-client software does not match server API!
You should update your client using:
$ pip3 install --upgrade "%(package)s==%(remote_version)d"
"""

def check_update(server):
    updated = False
    remote_version = server.get_remote_version()
    if remote_version != int(__version__):
        plugins = get_plugins()
        if len(plugins) > 0:
            package = 'walt-client[' + ','.join(plugins) + ']'
        else:
            package = 'walt-client'
        msg = MSG_UPDATE % dict(
                remote_version = remote_version,
                package = package)
        msg = highlight(msg)
        print()
        print(framed('Important notice', msg))
        print()
