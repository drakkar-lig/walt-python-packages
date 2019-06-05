from setuptools import setup, find_packages
import sys

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

# make sure we are executing the new info.py
exec(compile(open('walt/virtual/info.py').read(), 'walt/virtual/info.py', 'exec'))
SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)
