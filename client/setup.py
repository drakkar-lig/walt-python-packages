from setuptools import setup, find_packages
import sys

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

# make sure we are executing the new info.py
exec(compile(open('walt/client/info.py').read(), 'walt/client/info.py', 'exec'))
SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)
