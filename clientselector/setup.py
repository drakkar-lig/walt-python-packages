from setuptools import setup, find_packages
from walt.clientselector.info import SETUP_INFO

SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)