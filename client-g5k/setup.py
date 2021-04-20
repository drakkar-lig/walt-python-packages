import sys

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

from shutil import which

for cmd in ('oarsub', 'oarprint', 'kareboot3', 'kavlan'):
    if which(cmd) is None:
        sys.exit(("'%s' not found. " % cmd) + \
                 "walt-client with 'g5k' extension must be installed on a G5K frontend.")

from setuptools import setup, find_packages

# make sure we are executing the new info.py
exec(compile(open('walt/client/g5k/info.py').read(), 'walt/client/g5k/info.py', 'exec'))
SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)
