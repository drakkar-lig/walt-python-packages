import sys

from walt.common.version import __version__

MSG_UPDATE = """
walt-client software does not match server API!
You should update your client using:
$ pip3 install --upgrade "%(package)s==%(remote_version)s"
"""


def check_update(server):
    remote_version = str(server.get_remote_version())
    if remote_version != str(__version__):
        from walt.client.plugins import get_plugin_feature_names
        from walt.common.formatting import framed, highlight
        features = get_plugin_feature_names()
        if len(features) > 0:
            package = "walt-client[" + ",".join(features) + "]"
        else:
            package = "walt-client"
        msg = MSG_UPDATE % dict(remote_version=remote_version, package=package)
        msg = highlight(msg)
        print()
        print(framed("Important notice", msg))
        print()
        sys.exit(1)
