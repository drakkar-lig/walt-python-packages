from setuptools import setup, find_packages
import sys

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

# make sure we are executing the new info.py
execfile('walt/client/info.py')
SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)
