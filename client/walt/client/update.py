import os, subprocess
from walt.common.version import __version__
from walt.client.plugins import get_plugins

MSG_UPDATE = """
walt-client software does not match server API!
You should update your client using:
$ pip3 install --upgrade "%(package)s==%(remote_version)d"
"""

def highlight(section):
    lines = section.strip().splitlines()
    max_len = max(len(s) for s in lines)
    line_format = "*** %-" + str(max_len) + "s ***"
    if os.isatty(1):
        line_format = "\x1b[1;2m" + line_format + "\x1b[0m"
    print()
    for line in lines:
        print(line_format % line)

def check_update(server):
    updated = False
    remote_version = server.get_remote_version()
    if remote_version != int(__version__):
        plugins = get_plugins()
        if len(plugins) > 0:
            package = 'walt-client[' + ','.join(plugins) + ']'
        else:
            package = 'walt-client'
        highlight(MSG_UPDATE % dict(
                remote_version = remote_version,
                package = package))
