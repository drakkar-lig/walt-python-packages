from setuptools import setup, find_packages
import sys

if not sys.version_info[0] == 2:
    sys.exit("Sorry, Python 3 is not supported (yet)")

# make sure we are executing the new info.py
execfile('walt/virtual/info.py')
SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)
