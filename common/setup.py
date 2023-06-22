# auto-generated by dev/setup-updater.py
# using metadata from dev/metadata.py

import sys

from setuptools import find_packages, setup

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

setup_info = {
    "name": "walt-common",
    "version": "0.42",
    "install_requires": [
        "plumbum>=1.7.2",
        "requests>=2.21.0",
        "python-dateutil>=2.8.1",
        "pyyaml>=5.3.1",
    ],
    "author": "WalT developers",
    "author_email": "walt-contact@univ-grenoble-alpes.fr",
    "keywords": "WalT testbed",
    "license": "3-Clause BSD",
    "url": "https://walt-project.liglab.fr",
    "description": "WalT common python modules.",
}
setup_info.update(packages=find_packages())
setup(**setup_info)
