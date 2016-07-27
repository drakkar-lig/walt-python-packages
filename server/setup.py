from setuptools import setup, find_packages
from walt.server.info import SETUP_INFO
import sys

if not sys.version_info[0] == 2:
    sys.exit("Sorry, Python 3 is not supported (yet)")

SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)
