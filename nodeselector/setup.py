from setuptools import setup, find_packages
from walt.nodeselector.info import SETUP_INFO

SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)
